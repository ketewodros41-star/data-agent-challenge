import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_TYPE_MAP: Dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "mongodb": "mongodb",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
}

class ConfigManager:
    """Manages parsing of DB configs mapping and tools.yaml files."""
    
    def __init__(self, kb_path: Path, tools_yaml_path: Path):
        self.kb_path = kb_path
        self.tools_yaml_path = tools_yaml_path

    def _parse_yaml_simple(self, text: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        stack: list = [(-1, result)]

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            content = line.strip()
            if ":" not in content:
                continue
            key, sep, value = content.partition(":")
            key = key.strip()
            value = value.strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else result
            if value:
                parent[key] = value
            else:
                new_dict: Dict[str, Any] = {}
                parent[key] = new_dict
                stack.append((indent, new_dict))
        return result

    def _load_toolbox_yaml(self) -> Dict[str, Any]:
        if not self.tools_yaml_path.exists():
            return {}
        text = self.tools_yaml_path.read_text(encoding="utf-8")
        try:
            import yaml
            raw = yaml.safe_load(text)
            return raw if isinstance(raw, dict) else {}
        except ImportError:
            return self._parse_yaml_simple(text)
        except Exception:
            return {}

    def _load_toolbox_sources(self) -> Dict[str, Dict[str, Any]]:
        raw = self._load_toolbox_yaml()
        return raw.get("sources", {}) if raw else {}

    def _load_toolbox_tools(self) -> Dict[str, Dict[str, Any]]:
        raw = self._load_toolbox_yaml()
        return raw.get("tools", {}) if raw else {}

    def _toolbox_mcp_tool_for_source(self, source_name: str) -> str:
        for tool_name, tool_cfg in self._load_toolbox_tools().items():
            if isinstance(tool_cfg, dict) and tool_cfg.get("source") == source_name:
                return tool_name
        return ""

    def _toolbox_postgres_mcp_tool(self, dataset_name: str) -> str:
        sources = self._load_toolbox_sources()
        tools = self._load_toolbox_tools()

        pg_sources = {
            name: cfg for name, cfg in sources.items() if cfg.get("kind") == "postgres"
        }
        if not pg_sources:
            return "run_query"

        d = dataset_name.lower()

        def _source_matches(src_name: str, src_cfg: dict) -> bool:
            sname = src_name.lower()
            pg_db = src_cfg.get("database", "").lower()
            if d in sname or d in pg_db or sname in d or pg_db.replace("_", "") in d:
                return True
            words = [w for w in sname.split("_") + pg_db.split("_") if len(w) > 2 and w != "postgres"]
            return any(w in d for w in words)

        chosen_source_name = next(
            (name for name, cfg in pg_sources.items() if _source_matches(name, cfg)),
            next(iter(pg_sources.keys())),
        )

        for tool_name, tool_cfg in tools.items():
            if not isinstance(tool_cfg, dict):
                continue
            if tool_cfg.get("source") == chosen_source_name and tool_cfg.get("kind") == "postgres-execute-sql":
                return tool_name
        return "run_query"

    def _toolbox_sqlite_config(self, dataset_name: str) -> Optional[Tuple[str, str]]:
        return self._toolbox_file_config(dataset_name, "sqlite", ["*.db", "*.sqlite"])

    def _toolbox_duckdb_config(self, dataset_name: str) -> Optional[Tuple[str, str]]:
        return self._toolbox_file_config(dataset_name, "duckdb", ["*.duckdb", "*.db"])

    def _toolbox_file_config(self, dataset_name: str, kind: str, extensions: List[str]) -> Optional[Tuple[str, str]]:
        sources = self._load_toolbox_sources()
        for source_name, cfg in sources.items():
            if cfg.get("kind") != kind:
                continue
            container_path = cfg.get("database", "")
            if f"query_{dataset_name.lower()}" not in container_path:
                continue
            prefix = kind.upper()
            host_path = os.getenv(f"{prefix}_{dataset_name.upper()}", "")
            if not host_path:
                host_path = container_path
            host_path = os.path.expanduser(host_path)
            mcp_tool = self._toolbox_mcp_tool_for_source(source_name)
            return host_path, mcp_tool
            
        # If not in tools.yaml, try scanning DAB root directly
        dab_root = os.getenv("DAB_ROOT", "/DataAgentBench")
        dataset_dir = os.path.join(dab_root, f"query_{dataset_name.lower()}", "query_dataset")
        if os.path.isdir(dataset_dir):
            import glob
            for ext in extensions:
                matches = sorted(glob.glob(os.path.join(dataset_dir, ext)))
                if matches:
                    return matches[0], ""
        return None

    def parse_kb_dataset_registry(self) -> Dict[str, List[Dict[str, str]]]:
        if not self.kb_path.exists():
            return {}
        text = self.kb_path.read_text(encoding="utf-8")

        section_pat = re.compile(r"^##\s+\d+\.\s+(\S+)", re.MULTILINE)
        splits = list(section_pat.finditer(text))

        registry: Dict[str, List[Dict[str, str]]] = {}

        for idx, match in enumerate(splits):
            dataset_name = match.group(1).lower()
            section_start = match.start()
            section_end = splits[idx + 1].start() if idx + 1 < len(splits) else len(text)
            section_text = text[section_start:section_end]

            first_table_pat = re.compile(r"(?:^\|[^\n]*\n)+", re.MULTILINE)
            first_table_match = first_table_pat.search(section_text)
            table_text = first_table_match.group(0) if first_table_match else ""

            row_pat = re.compile(r"^\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|", re.MULTILINE)
            databases: List[Dict[str, str]] = []

            for row_match in row_pat.finditer(table_text):
                col1 = row_match.group(1).strip()
                col2 = row_match.group(2).strip()

                if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", col1):
                    continue
                if col1.lower() in ("database", "db", "databases"):
                    continue

                first_word = col2.lower().split()[0] if col2 else ""
                db_type = _TYPE_MAP.get(first_word, "")

                databases.append({"db_id": col1, "db_type": db_type})

            if databases:
                registry[dataset_name] = databases

        return registry

    def build_db_configs_from_env(
        self,
        databases_info: List[Dict[str, str]],
        dataset_name: str = "",
    ) -> Dict[str, dict]:
        configs: Dict[str, dict] = {}

        for entry in databases_info:
            db_id = entry["db_id"]
            kb_type = entry["db_type"]
            prefix = db_id.upper()

            db_type = os.getenv(f"{prefix}_DB_TYPE", kb_type).lower()

            if db_type in ("sqlite", "duckdb"):
                path = (
                    os.getenv(f"{prefix}_DB_PATH", "")
                    or os.getenv(f"{prefix}_DB_CONN", "")
                )
                mcp_tool = os.getenv(f"{prefix}_MCP_TOOL", "")

                if not path and dataset_name:
                    if db_type == "sqlite":
                        result = self._toolbox_sqlite_config(dataset_name)
                    else: # duckdb
                        result = self._toolbox_duckdb_config(dataset_name)
                        
                    if result:
                        path, mcp_tool = result

                if path:
                    path = os.path.expanduser(path)
                    cfg: dict = {"type": db_type, "path": path}
                    if mcp_tool:
                        cfg["mcp_tool"] = mcp_tool
                    configs[db_id] = cfg

            elif db_type in ("postgres", "postgresql"):
                mcp_tool = os.getenv(f"{prefix}_MCP_TOOL", "") or self._toolbox_postgres_mcp_tool(dataset_name or db_id)
                cfg: dict = {"type": "postgres"}
                if mcp_tool:
                    cfg["mcp_tool"] = mcp_tool
                configs[db_id] = cfg

            elif db_type == "mongodb":
                conn = os.getenv(f"{prefix}_DB_CONN", "") or os.getenv("MONGODB_URL", "")
                configs[db_id] = {"type": "mongodb", "connection_string": conn}

        return configs
