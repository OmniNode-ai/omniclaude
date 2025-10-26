"""
Manifest Injector - Load and inject system manifest into agent prompts.

Provides agents with complete system awareness at spawn:
- Available patterns (CRUD, Transformation, Orchestration, Aggregation)
- Infrastructure topology (PostgreSQL, Kafka, Qdrant, Archon MCP)
- Database schemas (15+ tables with columns)
- Event contracts (9+ Kafka topics)
- AI models and quorum configuration
- File structure and dependencies
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class ManifestInjector:
    """Load and format system manifest for agent context injection."""

    def __init__(self, manifest_path: Optional[str] = None):
        """
        Initialize manifest injector.

        Args:
            manifest_path: Path to system manifest YAML file.
                          Defaults to agents/system_manifest.yaml
        """
        if manifest_path is None:
            # Default to agents/system_manifest.yaml
            base_dir = Path(__file__).parent.parent
            resolved_path: Path = base_dir / "system_manifest.yaml"
            self.manifest_path = resolved_path
        else:
            self.manifest_path = Path(manifest_path)
        self._manifest: Optional[Dict[str, Any]] = None
        self._cached_formatted: Optional[str] = None

    def load_manifest(self) -> Dict[str, Any]:
        """
        Load system manifest from YAML file.

        Returns:
            Parsed manifest dictionary

        Raises:
            FileNotFoundError: If manifest file doesn't exist
            yaml.YAMLError: If manifest is invalid YAML
        """
        if self._manifest is not None:
            return self._manifest

        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"System manifest not found: {self.manifest_path}. "
                "Create it with: agents/system_manifest.yaml"
            )

        try:
            with open(self.manifest_path, "r") as f:
                self._manifest = yaml.safe_load(f)

            logger.info(f"Loaded system manifest from {self.manifest_path}")
            return self._manifest

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in manifest: {e}")
            raise

    def format_for_prompt(self, sections: Optional[list] = None) -> str:
        """
        Format manifest for injection into agent prompt.

        Args:
            sections: Optional list of section names to include.
                     If None, includes all sections.
                     Available: ['patterns', 'models', 'infrastructure',
                                'file_structure', 'dependencies', 'interfaces',
                                'agent_framework', 'skills']

        Returns:
            Formatted string ready for prompt injection
        """
        # Use cached version if available and no specific sections requested
        if sections is None and self._cached_formatted is not None:
            return self._cached_formatted

        manifest = self.load_manifest()

        # Build formatted output
        output = []
        output.append("=" * 70)
        output.append("SYSTEM MANIFEST - Complete Context for Agent Execution")
        output.append("=" * 70)
        output.append("")

        # Include requested sections or all if not specified
        available_sections = {
            "patterns": self._format_patterns,
            "models": self._format_models,
            "infrastructure": self._format_infrastructure,
            "file_structure": self._format_file_structure,
            "dependencies": self._format_dependencies,
            "interfaces": self._format_interfaces,
            "agent_framework": self._format_agent_framework,
            "skills": self._format_skills,
        }

        sections_to_include = sections or list(available_sections.keys())

        for section_name in sections_to_include:
            if section_name in available_sections:
                formatter = available_sections[section_name]
                section_output = formatter(manifest.get(section_name, {}))
                if section_output:
                    output.append(section_output)
                    output.append("")

        output.append("=" * 70)
        output.append("END SYSTEM MANIFEST")
        output.append("=" * 70)

        formatted = "\n".join(output)

        # Cache if all sections included
        if sections is None:
            self._cached_formatted = formatted

        return formatted

    def _format_patterns(self, patterns_data: Dict) -> str:
        """Format patterns section."""
        output = ["AVAILABLE PATTERNS:"]

        for pattern in patterns_data.get("available", []):
            output.append(
                f"  • {pattern['name']} ({pattern['confidence']:.0%} confidence)"
            )
            output.append(f"    File: {pattern['file']}")
            output.append(f"    Node Types: {', '.join(pattern['node_types'])}")
            use_cases = pattern.get("use_cases", [])
            if use_cases:
                output.append(f"    Use Cases: {', '.join(use_cases[:2])}...")

        return "\n".join(output)

    def _format_models(self, models_data: Dict) -> str:
        """Format models section."""
        output = ["AI MODELS & DATA MODELS:"]

        # AI Models
        if "ai_models" in models_data:
            output.append("  AI Providers:")
            for provider in models_data["ai_models"].get("providers", []):
                models_str = ", ".join(provider.get("models", []))
                output.append(f"    • {provider['name']}: {models_str}")

        # ONEX Models
        if "onex_models" in models_data:
            output.append("  ONEX Node Types:")
            for node_type in models_data["onex_models"].get("node_types", []):
                output.append(
                    f"    • {node_type['name']}: {node_type['naming_pattern']}"
                )

        return "\n".join(output)

    def _format_infrastructure(self, infra_data: Dict) -> str:
        """Format infrastructure section."""
        output = ["INFRASTRUCTURE TOPOLOGY:"]

        remote = infra_data.get("remote_services", {})

        # PostgreSQL
        if "postgresql" in remote:
            pg = remote["postgresql"]
            output.append(f"  PostgreSQL: {pg['host']}:{pg['port']}/{pg['database']}")
            tables = pg.get("tables", [])
            output.append(f"    Tables: {len(tables)} available")

        # Kafka (using bootstrap_servers)
        if "kafka" in remote:
            kafka = remote["kafka"]
            bootstrap = kafka.get("bootstrap_servers", "unknown")
            output.append(f"  Kafka: {bootstrap}")
            topics = kafka.get("topics", [])
            if topics:
                topic_names = [
                    t.get("name", t) if isinstance(t, dict) else t for t in topics[:3]
                ]
                topics_preview = ", ".join(topic_names)
                output.append(f"    Topics: {topics_preview}...")

        # Qdrant (using endpoint)
        local = infra_data.get("local_services", {})
        if "qdrant" in local:
            qdrant = local["qdrant"]
            endpoint = qdrant.get("endpoint", qdrant.get("host", "unknown"))
            output.append(f"  Qdrant: {endpoint}")
            collections = qdrant.get("collections", [])
            if collections:
                coll_names = [
                    c.get("name", c) if isinstance(c, dict) else c for c in collections
                ]
                output.append(f"    Collections: {', '.join(coll_names)}")

        return "\n".join(output)

    def _format_file_structure(self, file_data: Dict) -> str:
        """Format file structure section."""
        output = ["FILE STRUCTURE:"]

        # Handle root path if present
        if "root" in file_data:
            output.append(f"  Root: {file_data['root']}")

        # Handle directories
        directories = file_data.get("directories", {})
        for directory, info in directories.items():
            if isinstance(info, dict):
                description = info.get("description", "No description")
                output.append(f"  {directory}: {description}")

        return "\n".join(output)

    def _format_dependencies(self, deps_data: Dict) -> str:
        """Format dependencies section."""
        output = ["DEPENDENCIES:"]

        if "python_packages" in deps_data:
            packages = deps_data["python_packages"]
            output.append(f"  Python Packages: {len(packages)} installed")
            package_names = list(packages.keys())[:5]
            output.append(f"    Key: {', '.join(package_names)}...")

        return "\n".join(output)

    def _format_interfaces(self, interfaces_data: Dict) -> str:
        """Format interfaces section."""
        output = ["INTERFACES:"]

        if "databases" in interfaces_data:
            output.append("  Databases: PostgreSQL schemas documented")

        if "event_bus" in interfaces_data:
            output.append("  Event Bus: Kafka topics with event contracts")

        return "\n".join(output)

    def _format_agent_framework(self, framework_data: Dict) -> str:
        """Format agent framework section."""
        output = ["AGENT FRAMEWORK:"]

        if "quality_gates" in framework_data:
            gates = framework_data["quality_gates"]
            total_gates = gates.get("total_gates", 0)
            output.append(f"  Quality Gates: {total_gates} validation checks")

        if "mandatory_functions" in framework_data:
            funcs = framework_data["mandatory_functions"]
            total_funcs = funcs.get("total_functions", 0)
            output.append(f"  Mandatory Functions: {total_funcs} required")

        return "\n".join(output)

    def _format_skills(self, skills_data: Dict) -> str:
        """Format skills section."""
        output = ["AVAILABLE SKILLS:"]

        if "categories" in skills_data:
            for category, info in skills_data["categories"].items():
                count = info.get("count", 0)
                output.append(f"  {category}: {count} skills")

        return "\n".join(output)

    def get_manifest_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics about the manifest.

        Returns:
            Dictionary with counts and metadata
        """
        manifest = self.load_manifest()

        # Extract nested data for readability
        ai_models = manifest.get("models", {}).get("ai_models", {})
        infra = manifest.get("infrastructure", {}).get("remote_services", {})

        return {
            "version": manifest.get("manifest_metadata", {}).get("version"),
            "patterns_count": len(manifest.get("patterns", {}).get("available", [])),
            "ai_providers_count": len(ai_models.get("providers", [])),
            "database_tables_count": len(infra.get("postgresql", {}).get("tables", [])),
            "kafka_topics_count": len(infra.get("kafka", {}).get("topics", [])),
            "file_size_bytes": (
                self.manifest_path.stat().st_size if self.manifest_path.exists() else 0
            ),
        }


# Convenience function for quick access
def inject_manifest(sections: Optional[list] = None) -> str:
    """
    Quick function to load and format manifest.

    Args:
        sections: Optional list of sections to include

    Returns:
        Formatted manifest string
    """
    injector = ManifestInjector()
    return injector.format_for_prompt(sections)
