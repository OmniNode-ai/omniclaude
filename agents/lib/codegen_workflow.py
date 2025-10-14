#!/usr/bin/env python3
"""
Code Generation Workflow Integration

Integrates PRD analysis and template generation into the existing workflow.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID, uuid4
from pathlib import Path
from datetime import datetime

# Import from omnibase_core
from omnibase_core.errors import OnexError, CoreErrorCode

# Local imports
from .simple_prd_analyzer import SimplePRDAnalyzer, SimplePRDAnalysisResult
from .omninode_template_engine import OmniNodeTemplateEngine
from .version_config import get_config

logger = logging.getLogger(__name__)

class CodegenWorkflowResult:
    """Result of code generation workflow"""
    
    def __init__(
        self,
        session_id: UUID,
        correlation_id: UUID,
        prd_analysis: SimplePRDAnalysisResult,
        generated_nodes: List[Dict[str, Any]],
        total_files: int,
        success: bool,
        error_message: Optional[str] = None
    ):
        self.session_id = session_id
        self.correlation_id = correlation_id
        self.prd_analysis = prd_analysis
        self.generated_nodes = generated_nodes
        self.total_files = total_files
        self.success = success
        self.error_message = error_message
        self.completed_at = datetime.utcnow()

class CodegenWorkflow:
    """Code generation workflow orchestrator"""
    
    def __init__(self):
        self.config = get_config()
        self.prd_analyzer = SimplePRDAnalyzer()
        self.template_engine = OmniNodeTemplateEngine()
        self.logger = logging.getLogger(__name__)
    
    async def generate_from_prd(
        self,
        prd_content: str,
        output_directory: str,
        workspace_context: Optional[Dict[str, Any]] = None
    ) -> CodegenWorkflowResult:
        """
        Generate OmniNode implementations from PRD content.
        
        Args:
            prd_content: Raw PRD markdown content
            output_directory: Directory to write generated files
            workspace_context: Optional workspace context
            
        Returns:
            CodegenWorkflowResult with generation results
            
        Raises:
            OnexError: If generation fails
        """
        try:
            session_id = uuid4()
            correlation_id = uuid4()
            
            self.logger.info(f"Starting code generation workflow for session {session_id}")
            
            # Step 1: Analyze PRD
            self.logger.info("Step 1: Analyzing PRD content")
            prd_analysis = await self.prd_analyzer.analyze_prd(prd_content, workspace_context)
            
            # Step 2: Determine node types to generate
            self.logger.info("Step 2: Determining node types")
            node_types = self._determine_node_types(prd_analysis)
            
            # Step 3: Generate nodes
            self.logger.info("Step 3: Generating OmniNode implementations")
            generated_nodes = []
            total_files = 0
            
            for node_type in node_types:
                self.logger.info(f"Generating {node_type} node")
                
                # Extract microservice name and domain from PRD
                microservice_name = self._extract_microservice_name(prd_analysis)
                domain = self._extract_domain(prd_analysis)
                
                # Generate node
                node_result = await self.template_engine.generate_node(
                    analysis_result=prd_analysis,
                    node_type=node_type,
                    microservice_name=microservice_name,
                    domain=domain,
                    output_directory=output_directory
                )
                
                generated_nodes.append(node_result)
                total_files += len(node_result.get("generated_files", [])) + 1  # +1 for main file
            
            # Step 4: Validate generated code
            self.logger.info("Step 4: Validating generated code")
            validation_results = await self._validate_generated_code(generated_nodes)
            
            # Create result
            result = CodegenWorkflowResult(
                session_id=session_id,
                correlation_id=correlation_id,
                prd_analysis=prd_analysis,
                generated_nodes=generated_nodes,
                total_files=total_files,
                success=True
            )
            
            self.logger.info(f"Code generation workflow completed for session {session_id}")
            self.logger.info(f"Generated {len(generated_nodes)} nodes with {total_files} total files")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Code generation workflow failed: {str(e)}")
            return CodegenWorkflowResult(
                session_id=session_id if 'session_id' in locals() else uuid4(),
                correlation_id=correlation_id if 'correlation_id' in locals() else uuid4(),
                prd_analysis=None,
                generated_nodes=[],
                total_files=0,
                success=False,
                error_message=str(e)
            )
    
    def _determine_node_types(self, analysis_result: SimplePRDAnalysisResult) -> List[str]:
        """Determine which node types to generate based on analysis"""
        node_types = []
        
        # Get node type hints from analysis
        hints = analysis_result.node_type_hints
        
        # Add node types with confidence > 0.3
        for node_type, confidence in hints.items():
            if confidence > 0.3:
                node_types.append(node_type)
        
        # If no confident hints, default to EFFECT
        if not node_types:
            node_types = ["EFFECT"]
        
        # Limit to 2 nodes max for MVP
        return node_types[:2]
    
    def _extract_microservice_name(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Extract microservice name from PRD analysis"""
        # Use first word of title as microservice name
        title = analysis_result.parsed_prd.title
        if title:
            # Clean and extract first word
            words = title.lower().split()
            if words:
                # Remove common words and take first meaningful word
                meaningful_words = [w for w in words if w not in ['the', 'a', 'an', 'and', 'or', 'but']]
                if meaningful_words:
                    return meaningful_words[0]
        
        return "microservice"
    
    def _extract_domain(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Extract domain from PRD analysis"""
        # Use second word of title as domain, or default
        title = analysis_result.parsed_prd.title
        if title:
            words = title.lower().split()
            if len(words) > 1:
                return words[1]
        
        return "domain"
    
    async def _validate_generated_code(self, generated_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate generated code using omnibase_spi validators"""
        validation_results = {}
        
        for node in generated_nodes:
            node_type = node.get("node_type")
            microservice_name = node.get("microservice_name")
            
            # Validate metadata
            metadata = node.get("metadata", "")
            if metadata:
                validation_result = await self.prd_analyzer.validate_generated_metadata(metadata)
                validation_results[f"{microservice_name}_{node_type}"] = validation_result
        
        return validation_results
    
    async def generate_single_node(
        self,
        node_type: str,
        microservice_name: str,
        domain: str,
        business_description: str,
        output_directory: str
    ) -> Dict[str, Any]:
        """
        Generate a single node without full PRD analysis.
        
        Args:
            node_type: Type of node to generate
            microservice_name: Name of the microservice
            domain: Domain of the microservice
            business_description: Business description
            output_directory: Directory to write generated files
            
        Returns:
            Dictionary with generation results
        """
        try:
            # Create mock analysis result using simple models
            from .simple_prd_analyzer import SimpleParsedPRD, SimpleDecompositionResult
            
            mock_parsed_prd = SimpleParsedPRD(
                title=f"{microservice_name} {node_type}",
                description=business_description,
                functional_requirements=[f"Implement {microservice_name} {node_type.lower()} functionality"],
                features=[f"{microservice_name} {node_type.lower()} operations"],
                success_criteria=[f"Successful {microservice_name} {node_type.lower()} implementation"],
                technical_details=[f"{node_type} node implementation"],
                dependencies=[],
                extracted_keywords=[microservice_name, node_type.lower()],
                sections=[],
                word_count=len(business_description.split())
            )
            
            mock_decomposition = SimpleDecompositionResult(
                tasks=[],
                total_tasks=0,
                verification_successful=True
            )
            
            mock_analysis = SimplePRDAnalysisResult(
                session_id=uuid4(),
                correlation_id=uuid4(),
                prd_content=business_description,
                parsed_prd=mock_parsed_prd,
                decomposition_result=mock_decomposition,
                node_type_hints={node_type: 1.0},
                recommended_mixins=["MixinLogging", "MixinHealthCheck"],
                external_systems=[],
                quality_baseline=0.8,
                confidence_score=0.9
            )
            
            # Generate node
            result = await self.template_engine.generate_node(
                analysis_result=mock_analysis,
                node_type=node_type,
                microservice_name=microservice_name,
                domain=domain,
                output_directory=output_directory
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Single node generation failed: {str(e)}")
            raise OnexError(
                code=CoreErrorCode.OPERATION_FAILED,
                message=f"Single node generation failed: {str(e)}",
                details={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "domain": domain
                }
            )
