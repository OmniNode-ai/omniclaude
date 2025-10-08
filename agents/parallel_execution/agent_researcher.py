# agent_researcher.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any
# Assuming ArchonMCPClient is available in the environment
# from archon_mcp_client import ArchonMCPClient # Uncomment and import if available

# --- Pydantic Models for Structured Outputs ---

class SourceReference(BaseModel):
    source_name: str = Field(..., description="Name of the research source (e.g., RAG, Documentation, GitHub).")
    url: str | None = Field(None, description="URL of the source, if applicable.")
    excerpt: str | None = Field(None, description="A short excerpt from the source demonstrating relevance.")

class ResearchFindings(BaseModel):
    query: str = Field(..., description="The original research query.")
    summary: str = Field(..., description="A comprehensive summary of the findings.")
    references: List[SourceReference] = Field(default_factory=list, description="List of sources referenced in the findings.")
    raw_data: Dict[str, Any] | None = Field(None, description="Optional raw data from research sources.")

class ResearchQuery(BaseModel):
    topic: str = Field(..., description="The main topic or question for research.")
    keywords: List[str] = Field(default_factory=list, description="Keywords to refine the search.")
    depth: str = Field("medium", description="Desired depth of research (e.g., shallow, medium, deep).")
    sources_to_include: List[str] = Field(default_factory=lambda: ["all"], description="Specific sources to prioritize (e.g., RAG, documentation, code_examples).")

# --- Research Intelligence Agent ---

class ResearchIntelligenceAgent:
    def __init__(self):
        # Initialize ArchonMCPClient if used
        # self.mcp_client = ArchonMCPClient() # Uncomment if ArchonMCPClient is used
        pass

    async def perform_research(self, query: ResearchQuery) -> ResearchFindings:
        """Performs comprehensive research based on the given query."""
        print(f"Starting research for topic: {query.topic}")
        
        findings_summary = []
        references = []
        raw_source_data = {}

        # Example of RAG integration (requires ArchonMCPClient)
        if "RAG" in query.sources_to_include or "all" in query.sources_to_include:
            try:
                # rag_response = await self.mcp_client.query_rag(query.topic) # Placeholder for actual call
                rag_response = {"content": f"RAG findings for {query.topic}...", "url": "http://rag.example.com"}
                if rag_response:
                    findings_summary.append(f"RAG data: {rag_response['content']}")
                    references.append(SourceReference(source_name="RAG System", url=rag_response.get('url'), excerpt=rag_response['content'][:100]))
                    raw_source_data["RAG"] = rag_response
            except Exception as e:
                print(f"Error querying RAG: {e}")
                # Implement robust error handling

        # Example of documentation research
        if "documentation" in query.sources_to_include or "all" in query.sources_to_include:
            doc_content = f"Documentation search for '{query.topic}' revealed key concepts X, Y, Z."
            findings_summary.append(f"Documentation: {doc_content}")
            references.append(SourceReference(source_name="Project Docs", url="http://docs.example.com/" + query.topic.replace(' ', '_'), excerpt=doc_content[:100]))
            raw_source_data["documentation"] = doc_content

        # Example of code examples research
        if "code_examples" in query.sources_to_include or "all" in query.sources_to_include:
            code_example = f"Found code snippets related to '{query.topic}' in repository ABC."
            findings_summary.append(f"Code Examples: {code_example}")
            references.append(SourceReference(source_name="Code Repository", url="http://code.example.com/" + query.topic.replace(' ', '_') + "_examples", excerpt=code_example[:100]))
            raw_source_data["code_examples"] = code_example

        # Assemble the final summary
        final_summary = " ".join(findings_summary) if findings_summary else f"No specific findings for '{query.topic}' found based on requested sources."

        return ResearchFindings(
            query=query.topic,
            summary=final_summary,
            references=references,
            raw_data=raw_source_data
        )

# --- Example Usage ---
async def main():
    agent = ResearchIntelligenceAgent()
    research_query = ResearchQuery(
        topic="Pydantic model validation",
        keywords=["dataclasses", "type hints"],
        depth="deep",
        sources_to_include=["RAG", "documentation"]
    )
    
    results = await agent.perform_research(research_query)
    print("\n--- Research Results ---")
    print(results.model_dump_json(indent=2))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
