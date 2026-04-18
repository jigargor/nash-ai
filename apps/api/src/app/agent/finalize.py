from anthropic import AsyncAnthropic

from app.agent.loop import MODEL_NAME
from app.agent.schema import ReviewResult
from app.config import settings

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

FINAL_TOOL = {
    "name": "submit_review",
    "description": "Submit the final code review with all findings.",
    "input_schema": ReviewResult.model_json_schema(),
}


async def finalize_review(system_prompt: str, messages: list[dict], context: dict) -> ReviewResult:
    response = await client.messages.create(
        model=MODEL_NAME,
        max_tokens=8192,
        system=system_prompt,
        tools=[FINAL_TOOL],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=messages + [{"role": "user", "content": "Now submit your final review using the submit_review tool."}],
    )

    usage = response.usage
    context["input_tokens"] = context.get("input_tokens", 0) + usage.input_tokens
    context["output_tokens"] = context.get("output_tokens", 0) + usage.output_tokens
    context["tokens_used"] = context.get("tokens_used", 0) + usage.input_tokens + usage.output_tokens

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review":
            return ReviewResult.model_validate(block.input)
    raise RuntimeError("Model did not return submit_review tool output")
