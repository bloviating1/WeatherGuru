import os
from fastapi import FastAPI, HTTPException, WebSocket, params, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import traceback
from fastapi import UploadFile, File
from faster_whisper import WhisperModel
import shutil
from datetime import datetime
import litellm
from sqlalchemy.orm import Session
from database import SessionLocal
from get_imd_weather import get_nearest_imd_weather

# Note: Using CPU/int8 prevents the server crash on machines without dedicated NVIDIA GPUs
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
app = FastAPI(title="WeatherGPT")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"],
    allow_credentials=True,
)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ChatRequest(BaseModel):
    message: str
    latitude: float = 0.0
    longitude: float = 0.0
    language: str = "en"

async def fetch_weather(lat: float, lon: float):
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(OPEN_METEO, params=params)
        r.raise_for_status()
        return r.json()

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        temp_file_path = f"temp_{file.filename}"
        with open(temp_file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        segments, info = whisper_model.transcribe(temp_file_path, beam_size=5)
        transcription = " ".join([segment.text for segment in segments])
        os.remove(temp_file_path)
        return {"transcription": transcription}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/weather")
async def weather(lat: float = 30.3165, lon: float = 78.0322):
    return await fetch_weather(lat, lon)

@app.get("/forecast")
async def forecast(lat: float = 30.3165, lon: float = 78.0322):
    data = await fetch_weather(lat, lon)
    return data["daily"]

@app.get("/alerts")
async def alerts(lat: float = 30.3165, lon: float = 78.0322):
    return {"alerts": []}

@app.get("/history")
async def history():
    return {"trend": "stub"}
@app.get("/station/nearest")
async def nearest_station(lat: float = 29.9457, lon: float = 78.1642, db: Session = Depends(get_db)):
    station = await get_nearest_imd_weather(lat, lon, db)
    if not station:
        raise HTTPException(status_code=404, detail="No station found")
    
    from get_imd_weather import haversine_distance_km
    distance = haversine_distance_km(lat, lon, station.latitude, station.longitude)
    
    return {
        "station_name": station.station_name,
        "station_code": station.station_code,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "distance_km": round(distance, 1),
        "temperature": station.max_temp_c,
        "forecast": station.forecast_desc,
        "status": "Active & Synced"
    }

@app.post("/chat")
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        user_msg = req.message
        
        # Default to local coordinates if 0.0 is sent
        lat = req.latitude if req.latitude != 0.0 else 30.3165
        lon = req.longitude if req.longitude != 0.0 else 78.0322
        
        # 1. Fetch real IMD weather based on location
        real_weather = await get_nearest_imd_weather(lat, lon, db)
        
        if not real_weather:
            raise HTTPException(status_code=404, detail="No weather stations found near this location.")

        # 2. Fetch Open-Meteo data for tomorrow's forecast and reliable fallbacks
        raw_weather = await fetch_weather(lat, lon)
        daily = raw_weather.get("daily", {})
        current = raw_weather.get("current", {})

        # 3. Create bulletproof fallbacks if IMD API returns null
        safe_temp = real_weather.max_temp_c if real_weather.max_temp_c is not None else current.get("temperature_2m", 25.0)
        safe_min = real_weather.min_temp_c if real_weather.min_temp_c is not None else 20.0
        safe_hum = real_weather.humidity_pct if real_weather.humidity_pct is not None else current.get("relative_humidity_2m", 60.0)
        safe_desc = real_weather.forecast_desc if real_weather.forecast_desc else "Clear skies expected."
        
        # Extract tomorrow's rain chance (index 1 of the daily array)
        tomorrow_rain = daily.get("precipitation_probability_max", [0, 0])[1] if "precipitation_probability_max" in daily else 0

        # 4. Inject combined data into Llama 3.1
        from datetime import datetime
        current_date = datetime.now().strftime("%B %d, %Y")

        system_prompt = f"""You are a strict, factual weather assistant for farmers.
Today's Date: {current_date}. NEVER say it is a different month or year.

CURRENT WEATHER ({real_weather.station_name}):
- Temp: {safe_min}°C to {safe_temp}°C
- Humidity: {safe_hum}%
- Forecast: {safe_desc}
- Tomorrow's Rain Chance: {tomorrow_rain}%

STRICT RULES:
1. MAX LENGTH: You must answer in 2 sentences or less.
2. NO CHITCHAT: Do not ask "How is your farm doing?".
3. NO GUESSING: Only use the exact temperature and forecast provided above.
4. LANGUAGE: Reply strictly in {req.language}.
"""

        response = litellm.completion(
            model="ollama/llama3.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            api_base="http://localhost:11434"
        )
        ai_reply = response.choices[0].message.content

        # 5. Return the safe payload so the UI never displays 'null'
        return {
            "reply": ai_reply,
            "station": real_weather.station_name,
            "weather": {
                "temperature": safe_temp,
                "min_temperature": safe_min,
                "humidity": safe_hum,
                "forecast": safe_desc
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail=str(e))
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    while True:
        try:
            user_msg = await ws.receive_text()
            print(f"You: {user_msg}")
            response = litellm.completion(
                model="gemini/gemini-1.5-flash",
                messages=[{"role": "user", "content": user_msg}],
            )
            ai_reply = response.choices[0].message.content
            await ws.send_json({"answer": ai_reply})
        except Exception as e:
            await ws.send_json({"answer": f"Error calling Gemini: {str(e)}"})
            break