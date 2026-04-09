"""Salary Agent — handles salary recommendations."""

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from app.tools.salary_tools import get_salary_recommendation, get_all_salary_recommendations


salary_agent = Agent(
    name="salary_agent",
    model=LiteLlm(model="groq/llama-3.3-70b-versatile"),
    instruction="""You are the Salary Recommendation Agent for a household staff system.
You provide salary adjustment recommendations based on performance:

Rules:
- Score > 90: Recommend salary increase (10%)
- Score 70-90: No change recommended
- Score < 70: Consider reduction or issue a warning

Present recommendations clearly with reasoning.
Always show current salary, performance score, and suggested change.

Be professional and data-driven in your assessments.""",
    tools=[get_salary_recommendation, get_all_salary_recommendations],
)
