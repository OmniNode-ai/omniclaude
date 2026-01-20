"""
PRD Parser - Phase 1: Core PRD Analysis

High-performance parser for Product Requirements Documents (PRDs) that extracts
structured data from markdown documents.

Optimized for <1s parsing performance while maintaining accuracy.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from ..exceptions import CoreErrorCode, OnexError


@dataclass
class PRDSection:
    """Represents a parsed section from a PRD document."""

    title: str
    content: str
    level: int  # Header level (1-6)
    line_start: int
    line_end: int


class ModelParsedPRD(BaseModel):
    """
    Structured representation of a parsed PRD document.

    Contains all extracted information needed for node type classification
    and YAML ticket generation.
    """

    # Core identification
    title: str = Field(..., description="Document title")
    description: str = Field(..., description="Main description or overview")

    # Requirements and features
    functional_requirements: list[str] = Field(
        default_factory=list, description="Functional requirements list"
    )
    non_functional_requirements: list[str] = Field(
        default_factory=list, description="Non-functional requirements"
    )
    features: list[str] = Field(default_factory=list, description="Feature list")

    # Technical details
    technical_details: list[str] = Field(
        default_factory=list, description="Technical implementation details"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="External dependencies"
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Design assumptions"
    )

    # Business context
    business_value: str = Field(default="", description="Business value statement")
    success_criteria: list[str] = Field(
        default_factory=list, description="Success criteria and metrics"
    )

    # Keywords for classification
    extracted_keywords: set[str] = Field(
        default_factory=set, description="Keywords extracted for classification"
    )

    # Metadata
    sections: list[PRDSection] = Field(
        default_factory=list, description="All parsed sections"
    )
    word_count: int = Field(default=0, description="Total word count")
    parsing_timestamp: datetime = Field(
        default_factory=datetime.now, description="When document was parsed"
    )

    model_config = {"arbitrary_types_allowed": True}


class PRDParser:
    """
    High-performance PRD parser that extracts structured data from markdown documents.

    Features:
    - Fast markdown parsing optimized for PRD structure
    - Intelligent section recognition and content extraction
    - Keyword extraction for node type classification
    - Support for various PRD formats and conventions
    - Comprehensive error handling and validation
    """

    def __init__(self):
        """Initialize PRD parser with optimized patterns."""
        self._compile_regex_patterns()

        # Classification keyword mappings
        self.compute_keywords = {
            "process",
            "calculate",
            "compute",
            "transform",
            "analyze",
            "algorithm",
            "ml",
            "machine learning",
            "ai",
            "artificial intelligence",
            "model",
            "inference",
            "prediction",
            "classification",
            "regression",
            "neural",
            "data processing",
            "computation",
            "mathematical",
            "statistical",
        }

        self.effect_keywords = {
            "save",
            "store",
            "persist",
            "export",
            "send",
            "notify",
            "email",
            "database",
            "api",
            "write",
            "create",
            "update",
            "delete",
            "insert",
            "webhook",
            "integration",
            "external",
            "third party",
            "service",
            "file system",
            "storage",
            "backup",
            "sync",
            "publish",
        }

        self.reducer_keywords = {
            "aggregate",
            "combine",
            "merge",
            "collect",
            "accumulate",
            "sum",
            "count",
            "average",
            "metrics",
            "statistics",
            "reporting",
            "dashboard",
            "analytics",
            "kpi",
            "reduce",
            "group",
            "rollup",
            "summary",
        }

        self.orchestrator_keywords = {
            "coordinate",
            "orchestrate",
            "manage",
            "route",
            "workflow",
            "pipeline",
            "sequence",
            "parallel",
            "dispatch",
            "schedule",
            "broker",
            "mediator",
            "controller",
            "director",
            "supervisor",
            "automation",
            "process",
            "flow",
            "choreography",
            "saga",
        }

    def _compile_regex_patterns(self) -> None:
        """Compile regex patterns for efficient parsing."""
        # Header patterns (# ## ### etc.)
        self.header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

        # List item patterns (- * + 1. etc.)
        self.list_pattern = re.compile(r"^[\s]*[-*+•]\s+(.+)$", re.MULTILINE)
        self.numbered_list_pattern = re.compile(r"^[\s]*\d+\.\s+(.+)$", re.MULTILINE)

        # Requirements patterns
        self.requirement_patterns = {
            "functional": re.compile(
                r"(?:functional|feature|capability|shall|must|should)\s+requirement",
                re.IGNORECASE,
            ),
            "non_functional": re.compile(
                r"(?:non-?functional|performance|security|scalability|reliability)\s+requirement",
                re.IGNORECASE,
            ),
            "technical": re.compile(
                r"(?:technical|implementation|architecture|design)\s+(?:detail|requirement|specification)",
                re.IGNORECASE,
            ),
        }

        # Business context patterns
        self.business_value_pattern = re.compile(
            r"(?:business|value|benefit|impact|roi|return)", re.IGNORECASE
        )
        self.success_criteria_pattern = re.compile(
            r"(?:success|criteria|metric|kpi|goal|objective|measure)", re.IGNORECASE
        )

        # Dependency patterns
        self.dependency_pattern = re.compile(
            r"(?:depend|require|integrate|external|third[\s-]party|api|service)",
            re.IGNORECASE,
        )

    def parse(
        self, prd_content: str, title_override: str | None = None
    ) -> ModelParsedPRD:
        """
        Parse PRD content into structured format.

        Args:
            prd_content: Raw PRD markdown content
            title_override: Optional title to override extracted title

        Returns:
            ModelParsedPRD with extracted structured data

        Raises:
            OnexError: If prd_content is invalid or empty or not a string
        """
        # Enhanced input validation
        if not isinstance(prd_content, str):
            raise OnexError(
                code=CoreErrorCode.VALIDATION_ERROR,
                message="PRD content must be a string",
                details={"received_type": type(prd_content).__name__},
            )

        if not prd_content.strip():
            raise OnexError(
                code=CoreErrorCode.OPERATION_FAILED,
                message="PRD content cannot be empty or only whitespace",
                details={"content_length": len(prd_content)},
            )

        # Semantic validation: ensure content has meaningful structure
        stripped_content = prd_content.strip()
        if len(stripped_content) < 10:
            raise OnexError(
                code=CoreErrorCode.OPERATION_FAILED,
                message="PRD content must be at least 10 characters long",
                details={
                    "content_length": len(stripped_content),
                    "minimum_required": 10,
                },
            )

        # Check for basic markdown structure (at least one header or meaningful content)
        has_headers = bool(re.search(r"^#{1,6}\s+\w+", stripped_content, re.MULTILINE))
        has_content = len(stripped_content.split()) >= 3  # At least 3 words

        if not (has_headers or has_content):
            raise OnexError(
                code=CoreErrorCode.OPERATION_FAILED,
                message="PRD content must contain headers or meaningful text content",
                details={
                    "has_headers": has_headers,
                    "word_count": len(stripped_content.split()),
                    "minimum_words": 3,
                },
            )

        # Split into lines for processing
        lines = prd_content.split("\n")

        # Extract sections
        sections = self._extract_sections(lines)

        # Extract title
        title = title_override or self._extract_title(sections)

        # Extract structured content
        description = self._extract_description(sections)
        functional_requirements = self._extract_functional_requirements(sections)
        non_functional_requirements = self._extract_non_functional_requirements(
            sections
        )
        features = self._extract_features(sections)
        technical_details = self._extract_technical_details(sections)
        dependencies = self._extract_dependencies(sections)
        assumptions = self._extract_assumptions(sections)
        business_value = self._extract_business_value(sections)
        success_criteria = self._extract_success_criteria(sections)

        # Extract keywords for classification
        extracted_keywords = self._extract_classification_keywords(prd_content)

        # Calculate metadata
        word_count = len(prd_content.split())

        return ModelParsedPRD(
            title=title,
            description=description,
            functional_requirements=functional_requirements,
            non_functional_requirements=non_functional_requirements,
            features=features,
            technical_details=technical_details,
            dependencies=dependencies,
            assumptions=assumptions,
            business_value=business_value,
            success_criteria=success_criteria,
            extracted_keywords=extracted_keywords,
            sections=sections,
            word_count=word_count,
        )

    def _extract_sections(self, lines: list[str]) -> list[PRDSection]:
        """Extract all sections from markdown content."""
        sections = []
        current_section = None

        for i, line in enumerate(lines):
            header_match = self.header_pattern.match(line)

            if header_match:
                # Save previous section
                if current_section:
                    current_section.line_end = i - 1
                    current_section.content = current_section.content.strip()
                    sections.append(current_section)

                # Start new section
                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                current_section = PRDSection(
                    title=title, content="", level=level, line_start=i, line_end=i
                )

            elif current_section:
                # Add line to current section content
                current_section.content += line + "\n"

        # Don't forget the last section
        if current_section:
            current_section.line_end = len(lines) - 1
            current_section.content = current_section.content.strip()
            sections.append(current_section)

        return sections

    def _extract_title(self, sections: list[PRDSection]) -> str:
        """Extract document title from sections."""
        if not sections:
            return "Untitled PRD"

        # Look for the first level 1 header
        for section in sections:
            if section.level == 1:
                return section.title

        # If no level 1 header, use the first section title
        return sections[0].title if sections else "Untitled PRD"

    def _extract_description(self, sections: list[PRDSection]) -> str:
        """Extract main description/overview."""
        description_keywords = {
            "overview",
            "description",
            "summary",
            "introduction",
            "abstract",
        }

        # Look for sections with description-like titles
        for section in sections:
            if any(
                keyword in section.title.lower() for keyword in description_keywords
            ):
                # Extract first paragraph as description
                paragraphs = [
                    p.strip() for p in section.content.split("\n\n") if p.strip()
                ]
                if paragraphs:
                    return paragraphs[0]

        # If no description section, use first non-header content
        for section in sections:
            if section.content.strip():
                paragraphs = [
                    p.strip() for p in section.content.split("\n\n") if p.strip()
                ]
                if paragraphs:
                    return paragraphs[0]

        return ""

    def _extract_functional_requirements(self, sections: list[PRDSection]) -> list[str]:
        """Extract functional requirements from sections."""
        requirements = []

        # Look for functional requirements sections
        functional_keywords = {"functional", "feature", "capability", "requirement"}

        for section in sections:
            if any(keyword in section.title.lower() for keyword in functional_keywords):
                # Extract list items
                requirements.extend(self._extract_list_items(section.content))

        return requirements

    def _extract_non_functional_requirements(
        self, sections: list[PRDSection]
    ) -> list[str]:
        """Extract non-functional requirements."""
        requirements = []

        nfr_keywords = {
            "non-functional",
            "performance",
            "security",
            "scalability",
            "reliability",
            "quality",
        }

        for section in sections:
            if any(keyword in section.title.lower() for keyword in nfr_keywords):
                requirements.extend(self._extract_list_items(section.content))

        return requirements

    def _extract_features(self, sections: list[PRDSection]) -> list[str]:
        """Extract features list."""
        features = []

        feature_keywords = {"feature", "functionality", "capability", "component"}

        for section in sections:
            if any(keyword in section.title.lower() for keyword in feature_keywords):
                features.extend(self._extract_list_items(section.content))

        return features

    def _extract_technical_details(self, sections: list[PRDSection]) -> list[str]:
        """Extract technical implementation details."""
        details = []

        tech_keywords = {
            "technical",
            "implementation",
            "architecture",
            "design",
            "technology",
        }

        for section in sections:
            if any(keyword in section.title.lower() for keyword in tech_keywords):
                details.extend(self._extract_list_items(section.content))

        return details

    def _extract_dependencies(self, sections: list[PRDSection]) -> list[str]:
        """Extract dependencies and external integrations."""
        dependencies = []

        dep_keywords = {"dependency", "integration", "external", "service", "api"}

        for section in sections:
            if any(keyword in section.title.lower() for keyword in dep_keywords):
                dependencies.extend(self._extract_list_items(section.content))

        return dependencies

    def _extract_assumptions(self, sections: list[PRDSection]) -> list[str]:
        """Extract design assumptions."""
        assumptions = []

        assumption_keywords = {"assumption", "constraint", "limitation", "prerequisite"}

        for section in sections:
            if any(keyword in section.title.lower() for keyword in assumption_keywords):
                assumptions.extend(self._extract_list_items(section.content))

        return assumptions

    def _extract_business_value(self, sections: list[PRDSection]) -> str:
        """Extract business value statement."""
        business_keywords = {"business", "value", "benefit", "impact", "roi"}

        for section in sections:
            if any(keyword in section.title.lower() for keyword in business_keywords):
                paragraphs = [
                    p.strip() for p in section.content.split("\n\n") if p.strip()
                ]
                if paragraphs:
                    return paragraphs[0]

        return ""

    def _extract_success_criteria(self, sections: list[PRDSection]) -> list[str]:
        """Extract success criteria and metrics."""
        criteria = []

        success_keywords = {"success", "criteria", "metric", "kpi", "goal", "objective"}

        for section in sections:
            if any(keyword in section.title.lower() for keyword in success_keywords):
                criteria.extend(self._extract_list_items(section.content))

        return criteria

    def _extract_list_items(self, content: str) -> list[str]:
        """Extract list items from content (both bullet and numbered lists)."""
        items = []

        # Extract bullet point items
        bullet_matches = self.list_pattern.findall(content)
        items.extend([item.strip() for item in bullet_matches])

        # Extract numbered list items
        numbered_matches = self.numbered_list_pattern.findall(content)
        items.extend([item.strip() for item in numbered_matches])

        return items

    def _extract_classification_keywords(self, content: str) -> set[str]:
        """Extract keywords relevant for node type classification."""
        content_lower = content.lower()
        extracted = set()

        # Check for all keyword categories
        all_keywords = (
            self.compute_keywords
            | self.effect_keywords
            | self.reducer_keywords
            | self.orchestrator_keywords
        )

        for keyword in all_keywords:
            if keyword in content_lower:
                extracted.add(keyword)

        return extracted

    def get_classification_hints(self, parsed_prd: ModelParsedPRD) -> dict[str, float]:
        """
        Get classification hints based on extracted keywords.

        Args:
            parsed_prd: Parsed PRD data

        Returns:
            Dictionary mapping node types to hint scores (0-1)
        """
        hints = {"COMPUTE": 0.0, "EFFECT": 0.0, "REDUCER": 0.0, "ORCHESTRATOR": 0.0}

        keywords = parsed_prd.extracted_keywords

        if keywords:
            # Calculate scores based on keyword matches
            compute_matches = len(keywords & self.compute_keywords)
            effect_matches = len(keywords & self.effect_keywords)
            reducer_matches = len(keywords & self.reducer_keywords)
            orchestrator_matches = len(keywords & self.orchestrator_keywords)

            total_matches = (
                compute_matches
                + effect_matches
                + reducer_matches
                + orchestrator_matches
            )

            if total_matches > 0:
                hints["COMPUTE"] = compute_matches / total_matches
                hints["EFFECT"] = effect_matches / total_matches
                hints["REDUCER"] = reducer_matches / total_matches
                hints["ORCHESTRATOR"] = orchestrator_matches / total_matches

        return hints
