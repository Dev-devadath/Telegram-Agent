"""Task Agent — handles task assignment and tracking."""

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from app.tools.task_tools import assign_task, list_tasks, update_task_status, get_pending_tasks


task_agent = Agent(
    name="task_agent",
    model=LiteLlm(model="groq/llama-3.3-70b-versatile"),
    instruction="""You are the Task Management Agent for a household staff system.
You handle:
- Assigning tasks to workers
- Listing tasks (all, by worker, by status)
- Updating task status when workers respond
- Showing pending tasks

Available worker IDs: driver-1, driver-2, cook, massager, pa, social-media

When assigning tasks, always confirm the worker exists first.
When a worker says they completed a task, update the status to 'completed' and recommend requesting verification.

Be concise and professional in your responses.""",
    tools=[assign_task, list_tasks, update_task_status, get_pending_tasks],
)
