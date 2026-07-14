import os
import asyncio
import json
from typing import TypedDict, Annotated, Literal, Optional, Any
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.types import Command

load_dotenv()

# 1. Define shared state
class State(TypedDict):
    messages: Annotated[list, add_messages]
    revision_count: int  # FIX #1: Track revisions to prevent infinite loops


# Global variables for agents (will be set in main)
researcher_agent: Optional[Any] = None
writer_agent: Optional[Any] = None
editor_agent: Optional[Any] = None


def prune_messages(messages: list, max_messages: int = 10) -> list:
    """Keep only the most recent messages to prevent token limit errors.
    
    Args:
        messages: List of message objects
        max_messages: Maximum number of messages to keep (default 10)
    
    Returns:
        Pruned list of messages
    """
    if len(messages) <= max_messages:
        return messages
    
    # Keep the first message (user input) and the most recent max_messages-1
    return [messages[0]] + messages[-(max_messages - 1):]


# Node function for researcher
async def researcher_node(state: State) -> Command[Literal["writer", "__end__"]]:
    """Research node that hands off to writer."""
    print("\n" + "="*50)
    print("RESEARCHER NODE")
    print("="*50)
    
    response = await researcher_agent.ainvoke({"messages": state["messages"]})  # type: ignore
    
    # Debug: Print search results and tool usage
    print("\n--- Research Results ---")
    for msg in response["messages"]:
        # Check for tool calls (AI messages with tool_calls)
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tool_call in msg.tool_calls:
                print(f"\nTool Called: {tool_call.get('name', 'Unknown')}")
                print(f"Arguments: {tool_call.get('args', {})}")
        
        # Check for tool responses (ToolMessage)
        if msg.type == "tool":
            print(f"\nTool Response from: {getattr(msg, 'name', 'Unknown Tool')}")
            content_preview = str(msg.content)[:500] + "..." if len(str(msg.content)) > 500 else str(msg.content)
            print(f"Content: {content_preview}")
        
        # Print AI responses (but not tool calls)
        if msg.type == "ai" and not hasattr(msg, 'tool_calls'):
            print(f"\nResearcher Response:")
            print(f"{msg.content}")
    
    print("\n" + "="*50 + "\n")
    
    # PROBLEM #2 FIX: Preserve revision_count when handing off to writer
    # FIX #6: Prune old messages to prevent token limit errors
    pruned_messages = prune_messages(response["messages"])
    return Command(
        update={
            "messages": pruned_messages,
            "revision_count": state.get("revision_count", 0)
        },
        goto="writer"
    )


# Node function for writer
async def writer_node(state: State) -> Command[Literal["editor", "__end__"]]:
    """Writer node that hands off to editor."""
    print("\n" + "="*50)
    print("WRITER NODE")
    print("="*50)
    
    response = await writer_agent.ainvoke({"messages": state["messages"]})  # type: ignore
    
    # Print the written content
    final_message = response["messages"][-1]
    print(f"\nWriter Output:")
    print(f"{final_message.content}")
    print("\n" + "="*50 + "\n")
    
    # PROBLEM #2 FIX: Preserve revision_count when handing off to editor
    # FIX #6: Prune old messages to prevent token limit errors
    pruned_messages = prune_messages(response["messages"])
    return Command(
        update={
            "messages": pruned_messages,
            "revision_count": state.get("revision_count", 0)
        },
        goto="editor"
    )


# Node function for editor
async def editor_node(state: State) -> Command[Literal["writer", "__end__"]]:
    """Editor node that can hand back to writer or end."""
    print("\n" + "="*50)
    print("EDITOR NODE")
    print("="*50)
    
    response = await editor_agent.ainvoke({"messages": state["messages"]})  # type: ignore
    
    # Debug: Print editor feedback
    final_message = response["messages"][-1]
    print(f"\nEditor Feedback:")
    print(f"{final_message.content}")
    
    # PROBLEM #3 FIX: Track revision attempts and prevent infinite loops
    revision_limit = 2
    current_revisions = state.get("revision_count", 0) if isinstance(state.get("revision_count"), int) else 0
    
    # FIX #6: Prune old messages to prevent token limit errors
    pruned_messages = prune_messages(response["messages"])
    
    # Check if revision is needed AND we haven't exceeded the limit
    if "REVISE" in str(final_message.content) and current_revisions < revision_limit:
        print(f"\n⚠️  Editor requested REVISION ({current_revisions + 1}/{revision_limit}) - routing back to writer")
        print("="*50 + "\n")
        return Command(
            update={
                "messages": pruned_messages,
                "revision_count": current_revisions + 1
            },
            goto="writer"
        )
    
    if current_revisions >= revision_limit:
        print(f"\n⚠️  Max revisions ({revision_limit}) reached - approving content")
    else:
        print("\n✓ Editor approved - workflow complete")
    print("="*50 + "\n")
    
    return Command(
        update={
            "messages": pruned_messages,
            "revision_count": current_revisions
        },
        goto="__end__"
    )


async def main():
    """Run the multi-agent content creation workflow."""
    global researcher_agent, writer_agent, editor_agent
    
    try:
        # Check for required API keys
        if not os.getenv("GITHUB_TOKEN"):
            print("Error: GITHUB_TOKEN not found.")
            print("Add GITHUB_TOKEN=your-token to a .env file")
            return
        
        if not os.getenv("TAVILY_API_KEY"):
            print("Error: TAVILY_API_KEY not found.")
            print("Add TAVILY_API_KEY=your-key to a .env file")
            print("Get your API key from: https://app.tavily.com/")
            return
        
        # Initialize LLM
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            raise ValueError("GITHUB_TOKEN not found in environment variables")
        
        llm = ChatOpenAI(
            model="openai/gpt-4o-mini",
            temperature=0.7,
            base_url="https://models.github.ai/inference",
            api_key=github_token  # type: ignore
        )
        
        # Load prompts from your local filesystem
        with open("templates/researcher.json", "r") as f:
            researcher_data = json.load(f)
            researcher_prompt = researcher_data.get("template", "You are a helpful research assistant.")
        
        with open("templates/writer.json", "r") as f:
            writer_data = json.load(f)
            writer_prompt = writer_data.get("template", "You are a helpful writing assistant.")
        
        with open("templates/editor.json", "r") as f:
            editor_data = json.load(f)
            editor_prompt = editor_data.get("template", "You are a helpful editing assistant.")
        
        # FIX #4: Enhance researcher prompt to ensure tool usage
        researcher_prompt = researcher_prompt + "\n\n**IMPORTANT**: You MUST use the search tools available to you to find current, accurate information. Do not provide generic responses without searching."
        
        # Get Tavily API key from environment
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            raise ValueError("TAVILY_API_KEY not found in environment variables")
        
        # Create MCP client for Tavily
        research_client = MultiServerMCPClient({  # type: ignore
            "tavily": {
                "transport": "http",
                "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={tavily_api_key}",
            }
        })
        
        # Get tools from the client (await because it's async)
        researcher_tools = await research_client.get_tools()
        
        # PROBLEM #4 FIX: Validate that tools were loaded successfully
        if not researcher_tools:
            print("Error: No research tools available from Tavily MCP server")
            return
        
        print(f"Research tools: {[tool.name for tool in researcher_tools]}")
        
        # Create agents using create_agent (new API)
        researcher_agent = create_agent(
            llm, 
            tools=researcher_tools, 
            system_prompt=researcher_prompt
        )
        
        # Writer and editor don't need tools
        writer_agent = create_agent(
            llm, 
            tools=[],
            system_prompt=writer_prompt
        )

        editor_agent = create_agent(
            llm, 
            tools=[], 
            system_prompt=editor_prompt
        )
        
        # Build the Graph without manual edges (Edgeless Handoff)
        builder = StateGraph(State)
        builder.add_node("researcher", researcher_node)
        builder.add_node("writer", writer_node)
        builder.add_node("editor", editor_node)
        
        # Only need to set the entry point
        builder.add_edge(START, "researcher")
        graph = builder.compile()
        
        # Run the workflow
        print("\n" + "="*50)
        print("Starting Multi-Agent Content Creation Workflow")
        print("="*50 + "\n")
        
        user_input = input("Enter the topic that you would like to research: ")
        initial_message = HumanMessage(content=user_input)
        
        # FIX #5: Initialize revision_count in state
        result = await graph.ainvoke({
            "messages": [initial_message],
            "revision_count": 0
        })
        
        print("\n" + "="*50)
        print("Workflow Complete")
        print("="*50 + "\n")
        print("Final Output:")
        print(result["messages"][-1].content if result["messages"] else "No output")
        
    except FileNotFoundError as e:
        # PROBLEM #5 FIX: Handle file not found errors with clear guidance
        print(f"\n❌ Error: {e}")
        print("\n📍 To fix this issue:")
        print("  1. Navigate to the python-langchain directory")
        print("  2. Run: cd python-langchain")
        print("  3. Then run: python app.py")
        print(f"\n📁 Current working directory: {os.getcwd()}")
    except Exception as e:
        # PROBLEM #5 FIX: Handle general errors with better messaging
        print(f"\n❌ Error: {e}")
        print("\n🔍 Debug information:")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
