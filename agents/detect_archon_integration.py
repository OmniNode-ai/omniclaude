#!/usr/bin/env python3
"""
Script to detect which Claude Code agents have 4-phase Archon MCP integration.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

def analyze_agent_file(filepath: Path) -> Dict[str, any]:
    """Analyze an agent file for Archon MCP integration patterns."""
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Detection patterns for Archon MCP integration
    patterns = {
        '4_phase_framework': r'🚀 4-Phase Archon MCP Integration|@ARCHON_INTEGRATION.md',
        'establish_context_function': r'def establish_archon_.*_context\(\):|Context Function.*establish_archon',
        'archon_health_check': r'mcp__archon__health_check\(\)|@ARCHON_INTEGRATION.md',
        'archon_create_project': r'mcp__archon__create_project\(|@ARCHON_INTEGRATION.md',
        'archon_perform_rag_query': r'mcp__archon__perform_rag_query\(|Domain Query.*patterns',
        'archon_search_code_examples': r'mcp__archon__search_code_examples\(|Implementation Query',
        'archon_update_task': r'mcp__archon__update_task\(|Progress phases|Phase 3.*Progress Tracking',
        'archon_create_document': r'mcp__archon__create_document\(|Phase 4.*Knowledge Capture',
        'phase_1_init': r'Phase 1:.*Repository-Aware.*Initialization',
        'phase_2_research': r'Phase 2:.*Research-Enhanced.*Intelligence',
        'phase_3_tracking': r'Phase 3:.*Real-Time.*Progress Tracking|Progress phases',
        'phase_4_completion': r'Phase 4:.*Completion.*Knowledge Capture'
    }
    
    results = {}
    for pattern_name, pattern in patterns.items():
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        results[pattern_name] = len(matches) > 0
    
    # Calculate integration completeness score
    total_patterns = len(patterns)
    matched_patterns = sum(1 for match in results.values() if match)
    completeness_score = matched_patterns / total_patterns
    
    # Determine integration status
    if completeness_score >= 0.8:
        status = "FULLY_INTEGRATED"
    elif completeness_score >= 0.5:
        status = "PARTIALLY_INTEGRATED"  
    elif completeness_score >= 0.2:
        status = "BASIC_INTEGRATION"
    else:
        status = "NOT_INTEGRATED"
    
    return {
        'agent_name': filepath.stem,
        'status': status,
        'completeness_score': completeness_score,
        'matched_patterns': matched_patterns,
        'total_patterns': total_patterns,
        'pattern_details': results
    }

def scan_agents_directory(agents_dir: str) -> List[Dict]:
    """Scan all agent .md files in the directory."""
    
    agents_path = Path(agents_dir)
    if not agents_path.exists():
        raise FileNotFoundError(f"Agents directory not found: {agents_dir}")
    
    results = []
    
    # Find all agent .md files (excluding common/framework files)
    agent_files = []
    for md_file in agents_path.glob("*.md"):
        # Skip common framework files
        if md_file.name.startswith(("COMMON_", "FRAMEWORK_", "ONEX_", "ARCHON_", "INTEGRATION_")):
            continue
        # Only process agent files
        if md_file.name.startswith("agent-"):
            agent_files.append(md_file)
    
    # Analyze each agent file
    for agent_file in sorted(agent_files):
        try:
            analysis = analyze_agent_file(agent_file)
            results.append(analysis)
        except Exception as e:
            print(f"Error analyzing {agent_file.name}: {e}")
    
    return results

def print_summary_report(results: List[Dict]):
    """Print a comprehensive summary report."""
    
    # Group results by status
    status_groups = {}
    for result in results:
        status = result['status']
        if status not in status_groups:
            status_groups[status] = []
        status_groups[status].append(result)
    
    print("=" * 80)
    print("CLAUDE CODE AGENTS - ARCHON MCP INTEGRATION STATUS")
    print("=" * 80)
    
    # Summary statistics
    total_agents = len(results)
    fully_integrated = len(status_groups.get('FULLY_INTEGRATED', []))
    partially_integrated = len(status_groups.get('PARTIALLY_INTEGRATED', []))
    basic_integration = len(status_groups.get('BASIC_INTEGRATION', []))
    not_integrated = len(status_groups.get('NOT_INTEGRATED', []))
    
    print(f"\n📊 SUMMARY STATISTICS:")
    print(f"   Total Agents Analyzed: {total_agents}")
    print(f"   ✅ Fully Integrated: {fully_integrated}")
    print(f"   🔄 Partially Integrated: {partially_integrated}")
    print(f"   🟡 Basic Integration: {basic_integration}")
    print(f"   ❌ Not Integrated: {not_integrated}")
    print(f"   📈 Integration Rate: {((fully_integrated + partially_integrated) / total_agents * 100):.1f}%")
    
    # Detailed breakdown by status
    for status in ['FULLY_INTEGRATED', 'PARTIALLY_INTEGRATED', 'BASIC_INTEGRATION', 'NOT_INTEGRATED']:
        if status not in status_groups:
            continue
        
        agents = status_groups[status]
        if not agents:
            continue
        
        print(f"\n{get_status_emoji(status)} {status.replace('_', ' ').title()} ({len(agents)} agents):")
        print("-" * 60)
        
        for agent in sorted(agents, key=lambda x: x['completeness_score'], reverse=True):
            score = agent['completeness_score'] * 100
            patterns = agent['matched_patterns']
            total = agent['total_patterns']
            print(f"   {agent['agent_name']:<35} {score:5.1f}% ({patterns}/{total} patterns)")
    
    # Agents needing attention
    print(f"\n🎯 NEXT ACTIONS:")
    needs_work = status_groups.get('NOT_INTEGRATED', []) + status_groups.get('BASIC_INTEGRATION', [])
    if needs_work:
        print(f"   Agents needing 4-phase integration: {len(needs_work)}")
        for agent in sorted(needs_work, key=lambda x: x['agent_name']):
            print(f"   - {agent['agent_name']}")
    else:
        print("   🎉 All agents have integration!")

def get_status_emoji(status: str) -> str:
    """Get emoji for status."""
    emoji_map = {
        'FULLY_INTEGRATED': '✅',
        'PARTIALLY_INTEGRATED': '🔄', 
        'BASIC_INTEGRATION': '🟡',
        'NOT_INTEGRATED': '❌'
    }
    return emoji_map.get(status, '❓')

def main():
    """Main execution."""
    agents_directory = "/Users/jonah/.claude/agents"
    
    try:
        print("Scanning Claude Code agents for Archon MCP integration...")
        results = scan_agents_directory(agents_directory)
        print_summary_report(results)
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())