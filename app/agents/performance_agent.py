"""Performance Agent — handles analytics and metrics."""

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from app.tools.performance_tools import (
    get_worker_performance,
    get_all_workers_performance,
    get_productivity_trends,
    get_task_distribution,
)


performance_agent = Agent(
    name="performance_agent",
    model="gemini-2.5-flash",
    instruction="""You are the Performance Analytics Agent for a household staff system.
You provide insights on:
- Individual worker performance (score, completion rate, reliability)
- All workers performance overview
- Productivity trends (top performers, completion rates)
- Task distribution across roles

Present data clearly with key metrics highlighted.
When asked about performance, always include the performance score and completion rate.
Provide actionable insights when possible.

Be concise. Use bullet points for clarity.""",
    tools=[get_worker_performance, get_all_workers_performance, get_productivity_trends, get_task_distribution],
)
