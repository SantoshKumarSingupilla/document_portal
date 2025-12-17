#This script automates loading your API keys, configuration, embedding model and LLM model 
# dynamically from environment variables or YAML config.
import os
import sys
import json #Parse JSON data from environment (for API_KEYS)
from dotenv import load_dotenv
from utils.config_loader import load_config
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_openai import OpenAIEmbeddings
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from logger import GLOBAL_LOGGER as log #Centralized logger for structured logs
from exception.custom_exception import DocumentPortalException

# from logger.custom_logger import CustomLogger
# log = CustomLogger().get_logger(__name__)

#Works in both local and cloud (production) environments, 
# Loads API keys securely from .env or ECS secrets
class ApiKeyManager:
    REQUIRED_KEYS = ["GROQ_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"]

    def __init__(self):
        #create storage & read combined secret
        self.api_keys = {} #creates an empty dict to hold the loaded keys.
        raw = os.getenv("API_KEYS") #tries to read an environment variable named API_KEYS
#Some deployments (e.g., AWS ECS secrets) return a single JSON string containing many keys; 
# this checks for that first.        
#First, checks if a single environment variable API_KEYS exists.
#This is useful in AWS ECS or Docker where you pass all keys as one JSON string   
#Example combined secret stored as a single env var (string) 
# API_KEYS='{"GROQ_API_KEY":"groq-abc","GOOGLE_API_KEY":"g-google-xyz"}'

#If combined secret exists — try to parse JSON
        if raw:#If raw is not None, it attempts json.loads(raw) to convert the string into a Python object
            try:
                parsed = json.loads(raw)
                #If parsing succeeds but the result is not a dict, it raises a ValueError
                if not isinstance(parsed, dict):
                    raise ValueError("API_KEYS is not a valid JSON object")
 #If JSON parsing works → store in self.api_keys
 #If parsing fails → logs a warning and moves on             
                self.api_keys = parsed
                #On success: assigns the parsed dict to self.api_keys and logs success
                log.info("Loaded API_KEYS from ECS secret")
            except Exception as e:
                #On any failure: logs a warning and continues — it will later try the fallback
                log.warning("Failed to parse API_KEYS as JSON", error=str(e))


        # Fallback — try individual environment variables
# For each required key in REQUIRED_KEYS, if it wasn't loaded from the 
# combined JSON (self.api_keys.get(key) is falsy), it checks the environment variable with that exact name.

# If found, it stores that value into self.api_keys and logs that it loaded the individual key.       
        for key in self.REQUIRED_KEYS:
            if not self.api_keys.get(key):
                env_val = os.getenv(key)
                if env_val:
                    self.api_keys[key] = env_val
                    log.info(f"Loaded {key} from individual env var")

        # Final check — ensure no required key is missing
        missing = [k for k in self.REQUIRED_KEYS if not self.api_keys.get(k)]
#if not self.api_keys.get(k): If the key does not exist or its value is empty, include it in the list
        #Builds a list missing of any required keys still not present in self.api_keys
        if missing: #If missing is non-empty: Logs an error with the list of missing keys
            log.error("Missing required API keys", missing_keys=missing)
            raise DocumentPortalException("Missing API keys", sys)
        #Success logging — mask keys and show partial values
        log.info("API keys loaded", keys={k: v[:6] + "..." for k, v in self.api_keys.items()})

#Getter method: return a specific key or raise if missing
    def get(self, key: str) -> str:
        val = self.api_keys.get(key)
        if not val:
            raise KeyError(f"API key for {key} is missing")
        return val

#if v: v is not empty / not zero / not False / not None
#if not v: v is empty / zero / False / None

class ModelLoader:
    """
    Loads embedding models and LLMs based on config and environment.
    """

    def __init__(self):
        if os.getenv("ENV", "local").lower() != "production":
            load_dotenv()
            log.info("Running in LOCAL mode: .env loaded")
        else:
            log.info("Running in PRODUCTION mode")

        self.api_key_mgr = ApiKeyManager()
        self.config = load_config()
        log.info("YAML config loaded", config_keys=list(self.config.keys()))

    def load_embeddings(self):
        """
        Load and return embedding model from Google Generative AI.
        """
        try:
            model_name = self.config["embedding_model"]["model_name"]
            log.info("Loading embedding model", model=model_name)
            return GoogleGenerativeAIEmbeddings(model=model_name,
                                                google_api_key=self.api_key_mgr.get("GOOGLE_API_KEY")) #type: ignore
        except Exception as e:
            log.error("Error loading embedding model", error=str(e))
            raise DocumentPortalException("Failed to load embedding model", sys)

    def load_llm(self):
        """
        Load and return the configured LLM model.
        """
        llm_block = self.config["llm"]
        provider_key = os.getenv("LLM_PROVIDER", "openai")# "groq")#"google")#"openai")

        if provider_key not in llm_block:
            log.error("LLM provider not found in config", provider=provider_key)
            raise ValueError(f"LLM provider '{provider_key}' not found in config")

        llm_config = llm_block[provider_key]
        provider = llm_config.get("provider")
        model_name = llm_config.get("model_name")
        temperature = llm_config.get("temperature", 0.2)
        max_tokens = llm_config.get("max_output_tokens", 2048)

        log.info("Loading LLM", provider=provider, model=model_name)

        if provider == "google":
            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=self.api_key_mgr.get("GOOGLE_API_KEY"),
                temperature=temperature,
                max_output_tokens=max_tokens
            )

        elif provider == "groq":
            return ChatGroq(
                model=model_name,
                api_key=self.api_key_mgr.get("GROQ_API_KEY"), #type: ignore
                temperature=temperature,
            )

        elif provider == "openai":
            return ChatOpenAI(
                model=model_name,
                api_key=self.api_key_mgr.get("OPENAI_API_KEY"),
                temperature=temperature,
                max_tokens=max_tokens
            )

        else:
            log.error("Unsupported LLM provider", provider=provider)
            raise ValueError(f"Unsupported LLM provider: {provider}")


if __name__ == "__main__":
    loader = ModelLoader()

    # Test Embedding
    embeddings = loader.load_embeddings()
    print(f"Embedding Model Loaded: {embeddings}")
    result = embeddings.embed_query("Hello, how are you?")
    print(f"Embedding Result: {result}")

    # Test LLM
    llm = loader.load_llm()
    print(f"LLM Loaded: {llm}")
    result = llm.invoke("Hello, how are you?")
    print(f"LLM Result: {result.content}")
