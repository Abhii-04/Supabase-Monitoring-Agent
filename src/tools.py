from langchain_mcp_adapters.client import MultiServerMCPClient
from dotenv import load_dotenv
import os
from pathlib import Path
from langchain_experimental.tools import PythonREPLTool
from langchain_community.agent_toolkits import FileManagementToolkit


load_dotenv(override=True)
supabase=os.getenv("SUPABASE_ACCESS_TOKEN")

def get_file_tools():
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    toolkit = FileManagementToolkit(
        root_dir=str(reports_dir),
        selected_tools=["write_file", "read_file", "list_directory"],
    )
    return toolkit.get_tools()

async def get_tools():
    python_repl = PythonREPLTool()

    file_tools = get_file_tools()

    client=MultiServerMCPClient(
        {
            "supabase": {
            "command": "npx",
            "transport": "stdio",
            "args": [
                "-y",
                "@supabase/mcp-server-supabase@latest",
                "--read-only",
                "--project-ref=ifxubrjpqsufxkj"
            ],
            "env": {
                "SUPABASE_ACCESS_TOKEN": supabase
            }
            }
        }
    )

    supabase_tools = await client.get_tools()
    return [*supabase_tools, *file_tools, python_repl]



