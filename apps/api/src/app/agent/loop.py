from anthropic import AsyncAnthropic

from app.config import settings
from app.agent.tools import TOOLS, execute_tool

MAX_ITERATIONS = 10
MODEL_NAME = "claude-sonnet-4-5"
client = AsyncAnthropic(api_key=settings.anthropic_api_key)


async def run_agent(system_prompt: str, initial_user_message: str, context: dict) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": initial_user_message}]

    for _ in range(MAX_ITERATIONS):
        response = await client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        usage = response.usage
        context["input_tokens"] = context.get("input_tokens", 0) + usage.input_tokens
        context["output_tokens"] = context.get("output_tokens", 0) + usage.output_tokens
        context["tokens_used"] = context.get("tokens_used", 0) + usage.input_tokens + usage.output_tokens

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return messages

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = await execute_tool(block.name, block.input, context)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    return messages
