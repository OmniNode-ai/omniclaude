#!/usr/bin/env python3
"""
CRUD Pattern for Phase 5 Code Generation

Generates Create, Read, Update, Delete operations with database interaction,
input validation, error handling, and event publishing.
Typical for EFFECT nodes with database dependencies.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CRUDPattern:
    """
    CRUD operations pattern generator.

    Generates complete CRUD method implementations with:
    - Database interaction via transaction manager
    - Input validation
    - Error handling with OnexError
    - Event publishing (if EventBus mixin present)
    - Proper async/await patterns
    - Type hints and docstrings
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def matches(self, capability: dict[str, Any]) -> float:
        """
        Check if capability matches CRUD pattern.

        Args:
            capability: Capability dictionary from contract

        Returns:
            Confidence score (0.0 to 1.0)
        """
        crud_keywords = {
            "create",
            "insert",
            "add",
            "read",
            "get",
            "fetch",
            "update",
            "modify",
            "delete",
            "remove",
            "save",
            "store",
        }

        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )
        matched = sum(1 for kw in crud_keywords if kw in text)

        return min(matched / 3.0, 1.0)  # 3+ matches = 100% confidence

    def generate(self, capability: dict[str, Any], context: dict[str, Any]) -> str:
        """
        Generate CRUD method implementation.

        Args:
            capability: Capability dictionary from contract
            context: Additional generation context

        Returns:
            Generated Python code
        """
        operation = context.get("operation", "create")
        method_name = self._sanitize_method_name(capability.get("name", "execute"))
        description = capability.get("description", f"Execute {operation} operation")

        # Determine entity name from capability
        entity_name = self._extract_entity_name(capability, context)

        if operation == "create":
            return self._generate_create_method(
                method_name, description, entity_name, context
            )
        elif operation == "read":
            return self._generate_read_method(
                method_name, description, entity_name, context
            )
        elif operation == "update":
            return self._generate_update_method(
                method_name, description, entity_name, context
            )
        elif operation == "delete":
            return self._generate_delete_method(
                method_name, description, entity_name, context
            )
        else:
            # Generic CRUD method
            return self._generate_generic_crud_method(
                method_name, description, entity_name, context
            )

    def get_required_imports(self) -> list[str]:
        """Get required imports for CRUD pattern"""
        return [
            "from typing import Dict, Any, Optional, List",
            "from uuid import UUID, uuid4",
            "from omnibase_core.errors import OnexError, EnumCoreErrorCode",
            "import logging",
        ]

    def get_required_mixins(self) -> list[str]:
        """Get required mixins for CRUD pattern"""
        return [
            "MixinDatabase",  # Database transaction support
            "MixinValidation",  # Input validation
            "MixinEventBus",  # Event publishing (optional)
        ]

    def _generate_create_method(
        self,
        method_name: str,
        description: str,
        entity_name: str,
        context: dict[str, Any],
    ) -> str:
        """Generate CREATE operation method"""
        has_event_bus = context.get("has_event_bus", False)
        event_code = ""

        if has_event_bus:
            event_code = f"""
        # Publish event if EventBus mixin present
        if hasattr(self, "publish_event"):
            await self.publish_event(
                "{entity_name}.created",
                {{"entity_id": entity_id, "data": input_data.data}}
            )
"""

        return f'''
    async def {method_name}(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        {description}

        Creates a new {entity_name} record in the database.

        Args:
            input_data: Input data containing {entity_name} information

        Returns:
            Result dictionary with created entity ID and data

        Raises:
            OnexError: If creation fails or validation error occurs
        """
        try:
            self.logger.info(f"Creating {entity_name}: {{input_data}}")

            # Validate required fields
            required_fields = self._get_required_fields()
            for field in required_fields:
                if field not in input_data:
                    raise OnexError(
                        code=EnumCoreErrorCode.VALIDATION_ERROR,
                        message=f"Required field missing: {{field}}",
                        details={{"field": field, "input_data": input_data}}
                    )

            # Validate input data
            if hasattr(self, "validate_input"):
                validation_result = await self.validate_input(input_data)
                if not validation_result.get("valid", False):
                    raise OnexError(
                        code=EnumCoreErrorCode.VALIDATION_ERROR,
                        message="Input validation failed",
                        details=validation_result.get("errors", {{}})
                    )

            # Database operation with transaction
            async with self.transaction_manager.begin():
                entity_id = await self.db.insert("{entity_name.lower()}s", input_data)
                self.logger.info(f"{entity_name} created with ID: {{entity_id}}")
{event_code}
            return {{
                "success": True,
                "entity_id": str(entity_id),
                "message": f"{entity_name} created successfully",
                "data": input_data
            }}

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to create {entity_name}: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to create {entity_name}: {{str(e)}}",
                original_exception=e
            )

    def _get_required_fields(self) -> List[str]:
        """
        Get required fields for entity creation.

        Override this method in generated nodes to specify required fields
        based on the entity schema.

        Returns:
            List of required field names
        """
        # Default implementation - can be overridden by generated code
        # Common required fields for most entities
        return ["name", "description"]
'''

    def _generate_read_method(
        self,
        method_name: str,
        description: str,
        entity_name: str,
        context: dict[str, Any],
    ) -> str:
        """Generate READ operation method"""
        return f'''
    async def {method_name}(self, entity_id: str) -> Dict[str, Any]:
        """
        {description}

        Retrieves a {entity_name} record from the database.

        Args:
            entity_id: Unique identifier of the {entity_name}

        Returns:
            Result dictionary with {entity_name} data

        Raises:
            OnexError: If read fails or entity not found
        """
        try:
            self.logger.info(f"Reading {entity_name} with ID: {{entity_id}}")

            # Query database
            # Note: Table name is developer-controlled from ONEX entity definition
            result = await self.db.query_one(  # nosec B608
                "SELECT * FROM {entity_name.lower()}s WHERE id = $1",
                entity_id
            )

            if not result:
                raise OnexError(
                    code=EnumCoreErrorCode.NOT_FOUND,
                    message=f"{entity_name} not found: {{entity_id}}",
                    details={{"entity_id": entity_id}}
                )

            self.logger.info(f"{entity_name} retrieved: {{entity_id}}")

            return {{
                "success": True,
                "entity_id": entity_id,
                "data": dict(result)
            }}

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to read {entity_name}: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to read {entity_name}: {{str(e)}}",
                original_exception=e
            )
'''

    def _generate_update_method(
        self,
        method_name: str,
        description: str,
        entity_name: str,
        context: dict[str, Any],
    ) -> str:
        """Generate UPDATE operation method"""
        has_event_bus = context.get("has_event_bus", False)
        event_code = ""

        if has_event_bus:
            event_code = f"""
            # Publish update event
            if hasattr(self, "publish_event"):
                await self.publish_event(
                    "{entity_name}.updated",
                    {{"entity_id": entity_id, "data": update_data}}
                )
"""

        return f'''
    async def {method_name}(
        self,
        entity_id: str,
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        {description}

        Updates an existing {entity_name} record in the database.

        Args:
            entity_id: Unique identifier of the {entity_name}
            update_data: Updated {entity_name} data

        Returns:
            Result dictionary with updated {entity_name} data

        Raises:
            OnexError: If update fails or entity not found
        """
        try:
            self.logger.info(f"Updating {entity_name} with ID: {{entity_id}}")

            # Check entity exists
            # Note: Table name is developer-controlled from ONEX entity definition
            existing = await self.db.query_one(  # nosec B608
                "SELECT id FROM {entity_name.lower()}s WHERE id = $1",
                entity_id
            )

            if not existing:
                raise OnexError(
                    code=EnumCoreErrorCode.NOT_FOUND,
                    message=f"{entity_name} not found: {{entity_id}}",
                    details={{"entity_id": entity_id}}
                )

            # Database operation with transaction
            # Note: Table name is developer-controlled from ONEX entity definition
            async with self.transaction_manager.begin():
                await self.db.update(  # nosec B608
                    "{entity_name.lower()}s",
                    entity_id,
                    update_data
                )
                self.logger.info(f"{entity_name} updated: {{entity_id}}")
{event_code}
            return {{
                "success": True,
                "entity_id": entity_id,
                "message": f"{entity_name} updated successfully",
                "data": update_data
            }}

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to update {entity_name}: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to update {entity_name}: {{str(e)}}",
                original_exception=e
            )
'''

    def _generate_delete_method(
        self,
        method_name: str,
        description: str,
        entity_name: str,
        context: dict[str, Any],
    ) -> str:
        """Generate DELETE operation method"""
        has_event_bus = context.get("has_event_bus", False)
        event_code = ""

        if has_event_bus:
            event_code = f"""
            # Publish delete event
            if hasattr(self, "publish_event"):
                await self.publish_event(
                    "{entity_name}.deleted",
                    {{"entity_id": entity_id}}
                )
"""

        return f'''
    async def {method_name}(self, entity_id: str) -> Dict[str, Any]:
        """
        {description}

        Deletes a {entity_name} record from the database.

        Args:
            entity_id: Unique identifier of the {entity_name}

        Returns:
            Result dictionary confirming deletion

        Raises:
            OnexError: If deletion fails or entity not found
        """
        try:
            self.logger.info(f"Deleting {entity_name} with ID: {{entity_id}}")

            # Check entity exists
            # Note: Table name is developer-controlled from ONEX entity definition
            existing = await self.db.query_one(  # nosec B608
                "SELECT id FROM {entity_name.lower()}s WHERE id = $1",
                entity_id
            )

            if not existing:
                raise OnexError(
                    code=EnumCoreErrorCode.NOT_FOUND,
                    message=f"{entity_name} not found: {{entity_id}}",
                    details={{"entity_id": entity_id}}
                )

            # Database operation with transaction
            # Note: Table name is developer-controlled from ONEX entity definition
            async with self.transaction_manager.begin():
                await self.db.delete("{entity_name.lower()}s", entity_id)  # nosec B608
                self.logger.info(f"{entity_name} deleted: {{entity_id}}")
{event_code}
            return {{
                "success": True,
                "entity_id": entity_id,
                "message": f"{entity_name} deleted successfully"
            }}

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to delete {entity_name}: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to delete {entity_name}: {{str(e)}}",
                original_exception=e
            )
'''

    def _generate_generic_crud_method(
        self,
        method_name: str,
        description: str,
        entity_name: str,
        context: dict[str, Any],
    ) -> str:
        """Generate generic CRUD method stub"""
        return f'''
    async def {method_name}(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        {description}

        Performs {entity_name} operation.

        Args:
            input_data: Input data for the operation

        Returns:
            Result dictionary with operation result

        Raises:
            OnexError: If operation fails
        """
        try:
            self.logger.info(f"Executing {method_name}: {{input_data}}")

            # TODO: Implement {method_name} logic
            # This is a stub - implement based on specific requirements

            return {{
                "success": True,
                "message": f"{method_name} completed successfully",
                "data": input_data
            }}

        except Exception as e:
            self.logger.error(f"Failed to execute {method_name}: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to execute {method_name}: {{str(e)}}",
                original_exception=e
            )
'''

    def _sanitize_method_name(self, name: str) -> str:
        """Convert to valid Python method name"""
        import re

        name = re.sub(r"[^\w\s-]", "", name.lower())
        name = re.sub(r"[-\s]+", "_", name)
        return name.strip("_") or "execute_operation"

    def _extract_entity_name(
        self, capability: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """Extract entity name from capability or context"""
        # Try to extract from capability name
        name = capability.get("name", "")

        # Remove operation verbs
        for verb in ["create", "read", "update", "delete", "get", "fetch", "save"]:
            name = name.replace(verb, "").strip("_")

        return name.capitalize() or "Entity"
