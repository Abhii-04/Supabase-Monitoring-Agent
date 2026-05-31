from langgraph.prebuilt.tool_node import ToolNode
from src.tools import get_tools
from langchain.agents import create_agent
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from typing import Annotated, List,Any,Optional,Dict, TypedDict
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
import uuid
from datetime import datetime
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
load_dotenv(override=True)

llm=ChatOpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    model='deepseek-v4-flash' ,
    base_url = 'https://api.deepseek.com'
    )




class State(TypedDict):
    messages: Annotated[List[Any],add_messages]
    report: Optional[str]
    suspicious_activity:bool


class Agent:
    def __init__(self):
        self.worker_llm_with_tools=None
        self.tools = None
        self.graph=None
        self.sidekick_id = str(uuid.uuid4())
        self.memory=MemorySaver()
        
        

    async def setup(self):
        self.tools =  await get_tools()
        worker_llm=llm
        self.worker_llm_with_tools=worker_llm.bind_tools(self.tools)
        await self.build_graph()


    def worker(self,state:State) -> Dict[str, Any]:
        system_message = f"""You are an autonomous Supabase Monitoring Agent responsible for monitoring project logs, detecting suspicious activity, evaluating system health, and generating monitoring reports.

            # PRIMARY RESPONSIBILITIES

            Your responsibilities are:

            1. Review Supabase logs and system activity
            2. Detect suspicious behavior, failures, anomalies, crashes, abuse, or security issues
            3. Identify performance issues or repeated errors
            4. Generate concise markdown monitoring reports
            5. Save reports locally as `.md` files using the current timestamp as filename. Use the local file tools with filenames relative to the `reports/` directory.
            6. Summarize findings clearly and accurately

            # IMPORTANT OPERATING RULES

            You are operating in STRICT READ-ONLY MODE.

            You MUST NEVER:

            * Apply migrations
            * Modify databases
            * Alter schemas
            * Delete records
            * Insert records
            * Update records
            * Execute write queries
            * Execute destructive actions
            * Attempt repairs automatically
            * Modify Supabase configuration
            * Run dangerous commands
            * Call tools unrelated to monitoring

            You may ONLY:

            * Read logs
            * Inspect metadata
            * Analyze system status
            * Generate reports
            * Save markdown files locally

            If a tool attempts a write operation or migration:

            * STOP immediately
            * Do not retry the same action
            * Mark it as restricted
            * Continue with safe read-only analysis

            # TOOL USAGE POLICY

            Before calling a tool:

            1. Verify the tool is necessary
            2. Prefer read-only tools
            3. Avoid repeated tool calls
            4. Never retry failing dangerous operations
            5. Avoid loops and redundant actions

            If a tool fails:

            * Record the failure in the report
            * Continue safely when possible
            * Do not repeatedly retry the same failing tool

            # REPORT REQUIREMENTS

            Every monitoring session MUST produce a markdown report.

            The report must include:

            * Timestamp
            * Overall system status
            * Logs reviewed
            * Errors detected
            * Suspicious activity detected
            * Severity assessment
            * Recommended actions
            * Tool failures (if any)
            * Final summary

            # SUSPICIOUS ACTIVITY GUIDELINES

            Treat the following as suspicious:

            * Repeated authentication failures
            * Permission errors
            * Excessive API failures
            * Rate limit spikes
            * Database connection failures
            * Unexpected crashes
            * Unauthorized access attempts
            * Abnormally high error rates
            * Repeated 500 errors
            * Sudden traffic anomalies

            # EXECUTION STRATEGY

            Follow this workflow:

            1. Inspect logs
            2. Analyze findings
            3. Detect anomalies
            4. Generate summary
            5. Save markdown report
            6. Return final status

            # SUCCESS CRITERIA

            Your task is complete ONLY IF:

            * Logs were reviewed successfully
            * Analysis was completed
            * Markdown report was generated
            * Report was saved locally
            * Suspicious activity was identified if present
            * Final summary was produced

            # LOOP PREVENTION

            Do NOT repeatedly:

            * Call the same failing tool
            * Retry blocked operations
            * Re-analyze identical data
            * Enter unnecessary tool loops

            If sufficient information has already been collected:

            * Finish the task
            * Generate the report
            * End execution

            # RESPONSE STYLE

            Be:

            * concise
            * technical
            * accurate
            * operationally focused

            Do not:

            * hallucinate issues
            * invent logs
            * fabricate errors
            * claim successful actions that were not executed

            Only report verified findings.

        """
        messages = [
            SystemMessage( content= system_message),
            *state["messages"]
        ]


    
            
        response = self.worker_llm_with_tools.invoke(messages)
        return {
            "messages":[response]
        }
    def worker_router(self,state:State):

        last_message = state["messages"][-1]

        if hasattr(last_message,"tool_calls") and last_message.tool_calls:
            return "tools"

        return "end"


    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or item))
                else:
                    parts.append(str(item))
            return "\n".join(parts)

        return str(content)


    def _save_monitoring_report(self, result: Dict[str, Any]) -> str:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = reports_dir / f"monitoring-report-{timestamp}.md"

        final_message = result["messages"][-1]
        content = self._message_content_to_text(getattr(final_message, "content", final_message))
        if not content.strip():
            content = "No final monitoring summary was produced."

        report = (
            f"# Supabase Monitoring Report\n\n"
            f"Generated at: {datetime.now().isoformat(timespec='seconds')}\n\n"
            f"## Summary\n\n"
            f"{content.strip()}\n"
        )
        report_path.write_text(report, encoding="utf-8")
        return str(report_path)


      
    async def build_graph(self):
        graph_builder = StateGraph(State)

        tool_node = ToolNode(self.tools)

        graph_builder.add_node("worker",self.worker)
        graph_builder.add_node("tools", tool_node)
        
        graph_builder.add_conditional_edges(
            "worker",
            self.worker_router,
            {"tools":"tools","end":END}
        )

        graph_builder.add_edge("tools","worker")
        graph_builder.add_edge(START,"worker")


        self.graph = graph_builder.compile(checkpointer=self.memory)

    async def run_superstep(self, message="", suspicious_activity=False, history=None):
        config = {"configurable":{"thread_id": self.sidekick_id}}

        history = history or []
        state={
            "messages": [*history, {"role": "user", "content": message}],
            "report": None,
            "suspicious_activity" : suspicious_activity
        }
        result = await self.graph.ainvoke(state,config=config)
        result["report"] = self._save_monitoring_report(result)

        return result


            
        



    