import asyncio

from src.agent import Agent


async def setup():
    agent=Agent()
    await agent.setup()
    return agent


async def process_message(agent,message,suspicious_activity,history):
    result =  await agent.run_superstep(
        message,
        suspicious_activity,
        history
    )

    return result, agent


async def main():
    agent = await setup()
    result, _ = await process_message(
        agent,
        "view current logs and print summary",
        False,
        [],
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
