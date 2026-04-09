"""Verification Agent — handles secretary task verification."""

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from app.tools.verification_tools import request_verification, process_verification, get_pending_verifications


verification_agent = Agent(
    name="verification_agent",
    model=LiteLlm(model="groq/llama-3.3-70b-versatile"),
    instruction="""You are the Verification Agent for a household staff system.
You handle the secretary verification workflow:
- Requesting verification for completed tasks
- Processing secretary confirmations or rejections
- Listing pending verifications

When a task is reported completed, request verification from the secretary.
Present verification requests clearly with task details and timestamps.
Only mark tasks as truly completed after secretary confirmation.

Be concise and professional.""",
    tools=[request_verification, process_verification, get_pending_verifications],
)
