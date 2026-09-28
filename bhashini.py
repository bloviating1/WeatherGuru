import requests
USER_ID = "YOUR_USER_ID"
API_KEY = "YOUR_ULCA_API_KEY"
INFERENCE_KEY = "YOUR_INFERENCE_API_KEY"

def translate_text_bhashini(text: str, source_lang="en", target_lang="hi"):
    """
    Step 1: Pipeline Config Call
    Retrieves the dynamic inference endpoint and active model IDs.
    """
    config_url = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
    
    config_payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": source_lang,
                        "targetLanguage": target_lang
                    }
                }
            }
        ],
        "pipelineRequestConfig": {
            "pipelineId": "YOUR_PIPELINE_ID" # Found in your Bhashini project dashboard
        }
    }
    
    config_headers = {
        "userID": USER_ID,
        "ulcaApiKey": API_KEY,
        "Content-Type": "application/json"
    }
    
    config_res = requests.post(config_url, json=config_payload, headers=config_headers).json()
    
    # Extract the dynamic callback endpoint and required service ID
    callback_url = config_res["pipelineInferenceAPIEndPoint"]["callbackUrl"]
    service_id = config_res["pipelineResponseConfig"][0]["config"][0]["serviceId"]
    
    """
    Step 2: Pipeline Compute Call
    Executes the translation using the retrieved endpoint.
    """
    compute_payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": source_lang,
                        "targetLanguage": target_lang
                    },
                    "serviceId": service_id
                }
            }
        ],
        "inputData": {
            "input": [{"source": text}]
        }
    }
    
    # Bhashini dictates the exact header key name required for the Inference API Key
    dynamic_header_name = config_res["pipelineInferenceAPIEndPoint"]["inferenceApiKey"]["name"]
    
    compute_headers = {
        "Content-Type": "application/json",
        dynamic_header_name: INFERENCE_KEY
    }
    
    compute_res = requests.post(callback_url, json=compute_payload, headers=compute_headers).json()
    
    return compute_res["pipelineResponse"][0]["output"][0]["target"]