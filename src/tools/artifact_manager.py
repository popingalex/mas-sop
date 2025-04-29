import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger
from ruamel.yaml import YAML, YAMLError
import io

# --- REMOVED Global in-memory storage ---
# _artifact_storage: Dict[str, Any] = {}

class ArtifactManager:
    """Manages artifacts by saving/loading them as YAML files in a base directory."""

    def __init__(self, base_dir: Optional[Path | str] = None):
        """Initializes the ArtifactManager.

        Args:
            base_dir: The directory where artifacts will be stored. 
                      If None, uses a default 'artifacts' subdirectory in the current working directory.
        """
        if base_dir:
            self._base_dir = Path(base_dir)
        else:
            self._base_dir = Path("artifacts") # Default directory if none provided
        
        # Ensure the base directory exists
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"ArtifactManager initialized. Base directory: {self._base_dir.resolve()}")
        except OSError as e:
            logger.error(f"Failed to create artifact base directory {self._base_dir}: {e}")
            # Decide if this should be a fatal error
            raise # Re-raise for now

        self._yaml = YAML(typ='safe')
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml.preserve_quotes = True 

    def _get_artifact_path(self, name: str, event_id: Optional[str] = None) -> Path:
        """Constructs the file path for a given artifact name and optional event_id."""
        # Sanitize name for filesystem compatibility if needed (basic replacement)
        safe_name = name.replace('/', '_').replace('\\', '_').replace(':', '_')
        filename = f"{safe_name}.yaml"
        if event_id:
             # Sanitize event_id as well
             safe_event_id = event_id.replace('/', '_').replace('\\', '_').replace(':', '_')
             # Optionally create subdirectories per event_id? For now, prefix filename.
             filename = f"{safe_event_id}__{safe_name}.yaml" 
        return self._base_dir / filename

    async def save_artifact(self, data: Any, description: Optional[str] = None, name: Optional[str] = None, event_id: Optional[str] = None, preferred_format: str = 'yaml') -> Dict:
        """Saves an artifact to a file in the base directory.

        Args:
            data: The data to store (should be YAML serializable).
            description: A description used to generate the filename if 'name' is not provided.
            name: Explicit logical name for the artifact (used for filename generation). Overrides description if provided.
            event_id: Optional identifier for namespacing.
            preferred_format: Currently only 'yaml' is supported.

        Returns:
            A dictionary containing the artifact_id (filename) and path.
        """
        if preferred_format.lower() != 'yaml':
            logger.warning(f"ArtifactManager currently only supports YAML format, requested '{preferred_format}'. Saving as YAML.")

        if not name and not description:
             raise ValueError("Either 'name' or 'description' must be provided to save an artifact.")

        # Use name if provided, otherwise generate from description
        artifact_name = name if name else description
        if not artifact_name: # Should not happen due to check above, but as safeguard
             raise ValueError("Cannot determine artifact name.")

        file_path = self._get_artifact_path(artifact_name, event_id)
        
        logger.debug(f"Saving artifact '{artifact_name}' (Event: {event_id}) to file: {file_path}")

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # Add description as a comment if provided and name was used?
                if description and name:
                     f.write(f"# Description: {description}\n")
                self._yaml.dump(data, f)
            
            artifact_id = file_path.name # Use filename as the ID
            logger.info(f"Successfully saved artifact '{artifact_name}' as {artifact_id}")
            return {"artifact_id": artifact_id, "path": str(file_path)}
        except (OSError, YAMLError, TypeError) as e:
            logger.exception(f"Failed to save artifact '{artifact_name}' to {file_path}: {e}")
            # Decide return value on failure
            return {"artifact_id": None, "path": None, "error": str(e)}


    async def load_artifact(self, artifact_id: str) -> Optional[Any]:
        """Loads an artifact from a file using its ID (filename).

        Args:
            artifact_id: The ID (filename, e.g., 'report.yaml' or 'event1__report.yaml') of the artifact.

        Returns:
            The deserialized data, or None if not found or error occurs.
        """
        # Assume artifact_id is the filename directly
        file_path = self._base_dir / artifact_id
        logger.debug(f"Attempting to load artifact from file: {file_path}")

        if not file_path.exists() or not file_path.is_file():
             logger.warning(f"Artifact file not found: {file_path}")
             # Maybe try searching based on logical name if ID format is complex? For now, direct lookup.
             return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = self._yaml.load(f)
            logger.info(f"Successfully loaded artifact: {artifact_id}")
            return data
        except (OSError, YAMLError) as e:
            logger.exception(f"Failed to load or parse artifact from {file_path}: {e}")
            return None

    async def list_artifacts(self, event_id: Optional[str] = None) -> List[str]:
         """Lists available artifact IDs (filenames) in the base directory."""
         logger.debug(f"Listing artifacts in {self._base_dir} (Event filter: {event_id})")
         artifact_ids = []
         try:
             for item in self._base_dir.iterdir():
                 # Check if it's a file and ends with .yaml (or expected extension)
                 if item.is_file() and item.suffix.lower() == '.yaml':
                     if event_id:
                         # Check if filename starts with the event prefix
                         safe_event_id = event_id.replace('/', '_').replace('\\', '_').replace(':', '_')
                         prefix = f"{safe_event_id}__"
                         if item.name.startswith(prefix):
                             artifact_ids.append(item.name)
                     else:
                         # No event filter, add if it doesn't seem to be event-specific (or add all?)
                         # Let's add all YAML files if no event_id is given for now
                         artifact_ids.append(item.name)
             return artifact_ids
         except OSError as e:
              logger.error(f"Failed to list artifacts in {self._base_dir}: {e}")
              return []

# --- Placeholder for future Plan Manager Client ---
# This would interact with the WorkflowEngine or a separate planning service
# class PlanManagerClient:
#     def get_current_task(self, agent_name: str) -> Optional[Dict]: ...
#     def update_task_status(self, step_id: str, task_id: str, status: str, message: Optional[str] = None): ...
#     def create_sub_plan(self, parent_step_id: str, tasks: List[Dict]) -> str: ... 