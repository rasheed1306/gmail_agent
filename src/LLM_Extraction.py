import json
from datetime import datetime
from typing import Dict, Any, List
from chat_manager import ChatApplication
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from sample_response import User_1, User_2
import pathlib

'''
LLM-based Information Extraction Module for RAID Club
This module uses AI to extract structured information from club member conversations
including their major, motivation, and desired activities
'''

# Load environment variables from .env file in root directory
# Use absolute path to ensure .env is found regardless of current working directory
root_dir = pathlib.Path(__file__).parent.parent
load_dotenv(root_dir / ".env")


def extract_member_info_llm(conversation_data: Dict[str, Any], chat_app: ChatApplication) -> Dict[str, Any]:
    """
    Extract key member information from conversations using AI/LLM analysis.
    
    This function analyzes conversation data between club agents and potential members
    to extract structured information about their academic background, motivations,
    and club activity preferences. It only extracts information that is explicitly
    mentioned to avoid hallucination.
    
    Args:
        conversation_data: Dictionary containing member conversation data
            - email: Member's email address
            - name: Member's name  
            - conversation: Array of agent-user message exchanges
        chat_app: ChatApplication instance with LLM capabilities
        
    Returns:
        Dictionary containing extracted information:
            - email, name: Basic member details
            - major: Field of study (or "Not mentioned")
            - motivation: Reason for joining (or "Not mentioned")
            - desired_activities: List of activities they're interested in
            - conversation: Original conversation data for reference
    """
    try:
        # Combine all messages (both agent and user) into a single context
        all_messages: List[str] = []
        for msg in conversation_data.get("conversation", []):
            all_messages.append(f"Agent: {msg.get('agent', '')}")
            all_messages.append(f"User: {msg.get('user', '')}")
        
        conversation_text: str = "\n\n".join(all_messages)
        
        # Clear extraction prompt that emphasizes not to hallucinate
        extraction_prompt: str = f"""
        Analyze this conversation and extract ONLY information that is explicitly mentioned.
        
        Conversation:
        {conversation_text}
        
        Return a JSON object with these fields:
        {{
            "major": "their field of study (use 'Not mentioned' if not specified)",
            "motivation": "why they want to join (use 'Not mentioned' if not specified)", 
            "desired_activities": ["list of activities they specifically mentioned interest in"]
        }}
        
        CRITICAL: 
        - Only extract information that is clearly stated in the conversation
        - If something is not mentioned, use 'Not mentioned' or empty list []
        - Do NOT guess or infer information
        - Do NOT add information that isn't in the text
        - For desired_activities, return [] (empty list) if no activities are mentioned
        """
        
        # Get LLM response
        response = chat_app.llm_manager.generate_response([
            {"role": "system", "content": "You are a precise information extractor. Only extract what is explicitly stated. Never guess or add information. Return empty lists for missing data."},
            {"role": "user", "content": extraction_prompt}
        ])
        
        # Parse the LLM response as JSON
        response_content = response.content.strip() if response.content else ""
                
        # Remove markdown code blocks if present
        if response_content.startswith('```json'):
            response_content = response_content.replace('```json', '').replace('```', '').strip()
        elif response_content.startswith('```'):
            response_content = response_content.replace('```', '').strip()
        
        # Parse response
        extracted_info: Dict[str, Any] = json.loads(response_content)
        
        # Return clean result
        return {
            "email": conversation_data.get("email", ""),
            "name": conversation_data.get("name", ""),
            "major": extracted_info.get("major", "Not mentioned"),
            "motivation": extracted_info.get("motivation", "Not mentioned"),
            "desired_activities": extracted_info.get("desired_activities", []),
            "conversation": conversation_data.get("conversation", [])
        }
        
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse LLM response: {str(e)}",
            "email": conversation_data.get("email", ""),
            "name": conversation_data.get("name", ""),
            "major": "Not mentioned",
            "motivation": "Not mentioned", 
            "desired_activities": [],
            "conversation": conversation_data.get("conversation", [])
        }
    except Exception as e:
        return {
            "error": f"Extraction failed: {str(e)}",
            "email": conversation_data.get("email", ""),
            "name": conversation_data.get("name", ""),
            "major": "Not mentioned",
            "motivation": "Not mentioned",
            "desired_activities": [],
            "conversation": conversation_data.get("conversation", [])
        }


# Function schema for the extract_member_info_llm function
extract_member_info_llm_schema: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "extract_member_info_llm",
        "description": "Extract key member information (major, motivation, desired activities) from conversation data using LLM",
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_data": {
                    "type": "object",
                    "description": "Dictionary containing conversation information with email, name, and conversation array",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Member's email address"
                        },
                        "name": {
                            "type": "string", 
                            "description": "Member's name"
                        },
                        "conversation": {
                            "type": "array",
                            "description": "Array of conversation messages between agent and user",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "agent": {"type": "string"},
                                    "user": {"type": "string"},
                                    "timestamp": {"type": "string"}
                                }
                            }
                        }
                    },
                    "required": ["email", "name", "conversation"]
                },
                "chat_app": {
                    "type": "object",
                    "description": "ChatApplication instance for LLM interactions",
                    "properties": {
                        "api_key": {"type": "string"},
                        "model": {"type": "string"},
                        "endpoint": {"type": "string"}
                    }
                }
            },
            "required": ["conversation_data", "chat_app"]
        }
    }
}


def main():
    """
    Test function to test LLM extraction module.
    """

    chat_app = ChatApplication(api_key=os.getenv("OPENAI_API_KEY", ""), model=os.getenv("OPENAI_MODEL", ""), endpoint=os.getenv("OPENAI_ENDPOINT", ""))

    conversation_data = User_2
    result = extract_member_info_llm(conversation_data, chat_app)
    print(result)
    


if __name__ == "__main__":
    main()
