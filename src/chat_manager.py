from openai import OpenAI
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import json



# Define a class for managing LLM interactions
@dataclass
class LLMManager:
    api_key: str
    model: str 
    endpoint: str
    client: OpenAI = field(init=False)
    
    def __post_init__(self):
        self.client = OpenAI(api_key=self.api_key, base_url=self.endpoint)
    
    def get_model(self):
        return self.model
    
    def get_client(self):
        return self.client
    
    def get_endpoint(self):
        return self.endpoint

    def generate_response(self, messages, tools=None):
        """Generate a response from the LLM with optional tools."""
        if tools:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
        return response.choices[0].message

# Define a class for managing tools/functions
@dataclass
class ToolManager:
    tools: Dict[str, Any] = field(default_factory=dict)
    tool_schemas: List[Dict[str, Any]] = field(default_factory=list)

    def register_tool(self, func, func_schema):
        """Register a function as a tool."""
        name = func.__name__
        
        if func_schema is None:
            # Require explicit schema - no auto-generation
            raise ValueError(f"Function {name} requires explicit func_schema parameter")
        
        # Use provided func_schema
        schema = func_schema

        self.tools[name] = func
        self.tool_schemas.append(schema)
        return self

    def get_schemas(self):
        """Get all tool schemas."""
        return self.tool_schemas

    def execute_tool(self, name, arguments):
        """Execute a tool by name with given arguments."""
        if name not in self.tools:
            raise ValueError(f"Tool not found: {name}")

        func = self.tools[name]
        result = func(**arguments)
        return result

# Define a class for managing chat context
@dataclass
class ChatContext:
    messages: List[Dict[str, Any]] = field(init=False)
    # messages: List[Dict[str, Any]] = field(default_factory=lambda: [{"role": "system", "content": "You are a helpful assistant."}])
    system_message: str = "You are a helpful assistant."
    
    def __post_init__(self):
        self.messages = [{"role": "system", "content": self.system_message}]

    def add_user_message(self, content):
        """Add a user message to the context."""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, message):
        """Add an assistant message to the context."""
        self.messages.append({
            "role": "assistant",
            "content": message.content if hasattr(message, 'content') else message
        })

        # If this message contains tool calls, add them too
        if hasattr(message, 'tool_calls') and message.tool_calls:
            # Use model_dump() to convert Pydantic model to dict if needed
            if hasattr(message, 'model_dump'):
                self.messages[-1] = message.model_dump()

    def add_tool_result(self, tool_call_id, name, content):
        """Add a tool result to the context."""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content
        })

    def get_messages(self):
        """Get all messages in the context."""
        return self.messages

# Define a simple chat application that uses these components
@dataclass
class ChatApplication:
    api_key: str
    model: str
    endpoint: str
    system_message: str = "You are a helpful assistant."
    llm_manager: LLMManager = field(init=False)
    tool_manager: ToolManager = field(init=False)
    context: ChatContext = field(init=False)
    
    def __post_init__(self):
        self.llm_manager = LLMManager(self.api_key, self.model, self.endpoint)
        self.tool_manager = ToolManager()
        self.context = ChatContext(self.system_message)

    def register_tool(self, func, func_schema):
        """Register a function as a tool."""
        self.tool_manager.register_tool(func, func_schema)
        return self

    def process_user_input(self, user_input: str) -> str:
        """Process user input and return the assistant's response."""
        # Add user message to context
        self.context.add_user_message(user_input)

        # Get schemas for registered tools
        tool_schemas = self.tool_manager.get_schemas()

        # Get initial response from LLM
        response = self.llm_manager.generate_response(
            self.context.get_messages(),
            tools=tool_schemas if tool_schemas else None
        )

        # Add assistant's response to context
        self.context.add_assistant_message(response)

        # Check if any tool calls are requested
        if hasattr(response, 'tool_calls') and response.tool_calls:
            # Process each tool call
            for tool_call in response.tool_calls:
                function = getattr(tool_call, 'function', None)
                if not function:
                    continue
                function_name = getattr(function, 'name', None)
                args_raw = getattr(function, 'arguments', None)
                if not function_name or args_raw is None:
                    continue
                arguments = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                try:
                    # Execute the tool
                    result = self.tool_manager.execute_tool(function_name, arguments)

                    # Add tool result to context
                    tool_call_id = getattr(tool_call, 'id', None) or "tool_call"
                    self.context.add_tool_result(
                        tool_call_id,
                        function_name,
                        str(result) if not isinstance(result, dict) else json.dumps(result)
                    )
                except Exception as e:
                    # Handle errors
                    error_message = f"Error executing tool {function_name}: {str(e)}"
                    self.context.add_tool_result(tool_call_id, function_name, error_message)

            # Get final response from LLM with tool results
            final_response = self.llm_manager.generate_response(self.context.get_messages())

            # Add final response to context
            self.context.add_assistant_message(final_response)

            return final_response.content or ""
        else:
            # No tool calls, so return initial response
            return response.content or ""