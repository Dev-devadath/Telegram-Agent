"""Recommendation Agent — suggests next tasks for workers."""

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from app.tools.recommendation_tools import suggest_next_tasks, get_idle_workers


recommendation_agent = Agent(
    name="recommendation_agent",
    model=LiteLlm(model="groq/llama-3.3-70b-versatile"),
    instruction="""You are the Task Recommendation Agent for a household staff system.
You handle:
- Suggesting next tasks for workers based on their role
- Identifying idle workers who have no active tasks

When suggesting tasks, consider the worker's role and current workload.
Present suggestions as a clear numbered list.
If a worker is idle, proactively suggest tasks for them.

Be concise and helpful.""",
    tools=[suggest_next_tasks, get_idle_workers],
)
