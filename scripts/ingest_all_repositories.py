#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Multi-Repository Intelligence Ingestion Script

Ingests all Python files from multiple repositories into the Archon intelligence services
for comprehensive code analysis, pattern recognition, and search indexing.
"""

import concurrent.futures
import json
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from config import settings


class MultiRepositoryIngester:
    def __init__(
        self,
        base_url: str | None = None,
        search_url: str | None = None,
    ):
        self.base_url = base_url or str(settings.archon_intelligence_url)
        self.search_url = search_url or str(settings.archon_search_url)
        self.results = []
        self.lock = Lock()

        # Define repositories to process
        # Try to discover repositories dynamically
        self.repositories = self._discover_repositories()

    def _discover_repositories(self) -> dict[str, str]:
        """
        Discover repository paths dynamically.

        Priority:
        1. Environment variables (OMNI_REPOS_DIR or individual OMNI_<REPO>_PATH)
        2. Sibling directories to current repository
        3. Fallback to default paths (for backwards compatibility)
        """
        repos = {}
        repo_names = ["omnibase_core", "omnibase_spi", "omniarchon", "omninode_bridge"]

        # Check for base directory override
        base_dir = os.getenv("OMNI_REPOS_DIR")
        if base_dir:
            base_path = Path(base_dir)
            for repo_name in repo_names:
                repo_path = base_path / repo_name
                if repo_path.exists():
                    repos[repo_name] = str(repo_path)
            if repos:
                return repos

        # Try to find as sibling repositories
        current_repo = Path(__file__).parent.parent.resolve()  # omniclaude root
        parent_dir = current_repo.parent  # Code/ directory

        for repo_name in repo_names:
            # Check environment variable for specific repo
            env_var = f"OMNI_{repo_name.upper()}_PATH"
            env_path = os.getenv(env_var)
            if env_path and Path(env_path).exists():
                repos[repo_name] = env_path
                continue

            # Try sibling directory
            sibling_path = parent_dir / repo_name
            if sibling_path.exists():
                repos[repo_name] = str(sibling_path)

        return repos

    def find_python_files(self, root_dir: str) -> list[Path]:
        """Find all Python files in a repository."""
        python_files = []
        if not os.path.exists(root_dir):
            print(f"⚠️  Repository not found: {root_dir}")
            return python_files

        for root, dirs, files in os.walk(root_dir):
            # Skip certain directories
            skip_dirs = {
                ".git",
                "__pycache__",
                ".pytest_cache",
                "node_modules",
                "venv",
                ".venv",
                ".tox",
                "build",
                "dist",
            }
            dirs[:] = [d for d in dirs if d not in skip_dirs]

            for file in files:
                if file.endswith(".py"):
                    python_files.append(Path(root) / file)

        return python_files

    def analyze_code(self, file_path: Path, project_id: str) -> dict[str, Any]:
        """Analyze a single Python file for code quality and patterns."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            response = requests.post(
                f"{self.base_url}/assess/code",
                json={
                    "content": content,
                    "language": "python",
                    "source_path": str(file_path),
                },
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "file_path": str(file_path),
                    "project_id": project_id,
                    "success": True,
                    "analysis": result,
                }
            else:
                return {
                    "file_path": str(file_path),
                    "project_id": project_id,
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                }

        except Exception as e:
            return {
                "file_path": str(file_path),
                "project_id": project_id,
                "success": False,
                "error": str(e),
            }

    def index_document(self, file_path: Path, project_id: str) -> dict[str, Any]:
        """Index a file for search."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Determine component type based on path
            relative_path = str(file_path)
            if "tests/" in relative_path or "test_" in relative_path:
                component_type = "tests"
            elif "lib/" in relative_path or "utils/" in relative_path:
                component_type = "library"
            elif "config/" in relative_path or "configs/" in relative_path:
                component_type = "config"
            elif "templates/" in relative_path:
                component_type = "templates"
            elif "examples/" in relative_path or "demos/" in relative_path:
                component_type = "examples"
            else:
                component_type = "core"

            response = requests.post(
                f"{self.base_url}/process/document",
                json={
                    "document_id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "content": content,
                    "source_path": str(file_path),
                    "language": "python",
                    "metadata": {
                        "component": component_type,
                        "type": "source_code",
                        "file_size": len(content),
                        "lines": len(content.splitlines()),
                        "repository": project_id,
                    },
                },
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "file_path": str(file_path),
                    "project_id": project_id,
                    "success": True,
                    "indexing": result,
                }
            else:
                return {
                    "file_path": str(file_path),
                    "project_id": project_id,
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                }

        except Exception as e:
            return {
                "file_path": str(file_path),
                "project_id": project_id,
                "success": False,
                "error": str(e),
            }

    def process_file(self, file_path: Path, project_id: str) -> dict[str, Any]:
        """Process a single file for both analysis and indexing."""
        print(f"Processing: {project_id}/{file_path.name}")

        # Analyze the code
        analysis_result = self.analyze_code(file_path, project_id)

        # Index the document
        indexing_result = self.index_document(file_path, project_id)

        # Combine results
        result = {
            "file_path": str(file_path),
            "project_id": project_id,
            "analysis": analysis_result,
            "indexing": indexing_result,
            "processed_at": time.time(),
        }

        with self.lock:
            self.results.append(result)

        return result

    def ingest_repository(
        self, repo_name: str, repo_path: str, max_workers: int = 3, batch_size: int = 5
    ):
        """Ingest a single repository."""
        print(f"\n🔍 Processing {repo_name}...")
        print(f"📁 Path: {repo_path}")

        python_files = self.find_python_files(repo_path)
        if not python_files:
            print(f"⚠️  No Python files found in {repo_name}")
            return None

        print(f"📊 Found {len(python_files)} Python files")

        start_time = time.time()

        # Process files in batches
        for i in range(0, len(python_files), batch_size):
            batch = python_files[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(python_files) + batch_size - 1) // batch_size
            print(
                f"  Processing batch {batch_num}/{total_batches} ({len(batch)} files)"
            )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                futures = [
                    executor.submit(self.process_file, file_path, repo_name)
                    for file_path in batch
                ]

                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                        if result["analysis"]["success"]:
                            analysis = result["analysis"]["analysis"]
                            print(
                                f"    ✅ {result['file_path']} - Quality: {analysis.get('quality_score', 0):.3f}"
                            )
                        else:
                            print(
                                f"    ❌ {result['file_path']} - Analysis failed: {result['analysis']['error']}"
                            )

                        if result["indexing"]["success"]:
                            print(
                                f"    📚 {result['file_path']} - Indexed successfully"
                            )
                        else:
                            print(
                                f"    ❌ {result['file_path']} - Indexing failed: {result['indexing']['error']}"
                            )

                    except Exception as e:
                        print(f"    ❌ Error processing file: {e}")

            # Small delay between batches
            if i + batch_size < len(python_files):
                time.sleep(0.5)

        end_time = time.time()
        duration = end_time - start_time

        print(f"✅ {repo_name} completed in {duration:.1f} seconds")
        return len(python_files)

    def ingest_all_repositories(self):
        """Ingest all repositories."""
        print("🚀 Multi-Repository Intelligence Ingestion")
        print("=" * 60)

        total_files = 0
        total_time = time.time()

        for repo_name, repo_path in self.repositories.items():
            try:
                files_processed = self.ingest_repository(repo_name, repo_path)
                total_files += files_processed
            except Exception as e:
                print(f"❌ Failed to process {repo_name}: {e}")
                continue

        end_time = time.time()
        total_duration = end_time - total_time

        print("\n🎉 All repositories ingestion complete!")
        print(f"⏱️  Total time: {total_duration:.1f} seconds")
        print(f"📊 Total files processed: {total_files}")

        # Generate comprehensive summary
        self.generate_comprehensive_summary()

    def generate_comprehensive_summary(self):
        """Generate a comprehensive summary of all repositories."""
        successful_analyses = [r for r in self.results if r["analysis"]["success"]]
        successful_indexings = [r for r in self.results if r["indexing"]["success"]]

        print("\n📈 COMPREHENSIVE INGESTION SUMMARY")
        print(
            f"  Analysis Success: {len(successful_analyses)}/{len(self.results)} ({len(successful_analyses) / len(self.results) * 100:.1f}%)"
        )
        print(
            f"  Indexing Success: {len(successful_indexings)}/{len(self.results)} ({len(successful_indexings) / len(self.results) * 100:.1f}%)"
        )

        # Repository breakdown
        repo_stats = {}
        for result in self.results:
            repo = result["project_id"]
            if repo not in repo_stats:
                repo_stats[repo] = {
                    "total": 0,
                    "analyzed": 0,
                    "indexed": 0,
                    "quality_scores": [],
                }

            repo_stats[repo]["total"] += 1
            if result["analysis"]["success"]:
                repo_stats[repo]["analyzed"] += 1
                quality_score = result["analysis"]["analysis"].get("quality_score", 0)
                repo_stats[repo]["quality_scores"].append(quality_score)
            if result["indexing"]["success"]:
                repo_stats[repo]["indexed"] += 1

        print("\n📊 REPOSITORY BREAKDOWN")
        for repo, stats in repo_stats.items():
            avg_quality = (
                sum(stats["quality_scores"]) / len(stats["quality_scores"])
                if stats["quality_scores"]
                else 0
            )
            print(f"  {repo}:")
            print(f"    Files: {stats['total']}")
            print(
                f"    Analyzed: {stats['analyzed']} ({stats['analyzed'] / stats['total'] * 100:.1f}%)"
            )
            print(
                f"    Indexed: {stats['indexed']} ({stats['indexed'] / stats['total'] * 100:.1f}%)"
            )
            print(f"    Avg Quality: {avg_quality:.3f}")

        if successful_analyses:
            # Overall quality analysis
            quality_scores = [
                r["analysis"]["analysis"]["quality_score"] for r in successful_analyses
            ]
            avg_quality = sum(quality_scores) / len(quality_scores)

            # Find best and worst files across all repos
            best_file = max(
                successful_analyses,
                key=lambda x: x["analysis"]["analysis"]["quality_score"],
            )
            worst_file = min(
                successful_analyses,
                key=lambda x: x["analysis"]["analysis"]["quality_score"],
            )

            print("\n🎯 OVERALL CODE QUALITY INSIGHTS")
            print(f"  Average Quality Score: {avg_quality:.3f}")
            print(
                f"  Best File: {best_file['project_id']}/{best_file['file_path']} (Score: {best_file['analysis']['analysis']['quality_score']:.3f})"
            )
            print(
                f"  Worst File: {worst_file['project_id']}/{worst_file['file_path']} (Score: {worst_file['analysis']['analysis']['quality_score']:.3f})"
            )

            # Pattern analysis across all repositories
            all_patterns = []
            for result in successful_analyses:
                patterns = result["analysis"]["analysis"].get("code_patterns", [])
                all_patterns.extend(patterns)

            if all_patterns:
                pattern_counts = {}
                for pattern in all_patterns:
                    pattern_name = pattern.get("pattern_name", "unknown")
                    pattern_type = pattern.get("pattern_type", "unknown")
                    key = f"{pattern_name} ({pattern_type})"
                    pattern_counts[key] = pattern_counts.get(key, 0) + 1

                print("\n🔍 CROSS-REPOSITORY PATTERN ANALYSIS")
                print(f"  Total Patterns Detected: {len(all_patterns)}")
                print(f"  Unique Pattern Types: {len(pattern_counts)}")

                # Show top patterns
                top_patterns = sorted(
                    pattern_counts.items(), key=lambda x: x[1], reverse=True
                )[:15]
                print("  Top Patterns Across All Repositories:")
                for pattern, count in top_patterns:
                    print(f"    {pattern}: {count}")

        # Save results to file
        results_file = "multi_repository_ingestion_results.json"
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n💾 Results saved to: {results_file}")


def main():
    """Main entry point."""
    print("🚀 Multi-Repository Intelligence Ingestion")
    print("Processing: omnibase_core, omnibase_spi, omniarchon, omninode_bridge")
    print("=" * 80)

    ingester = MultiRepositoryIngester()

    try:
        ingester.ingest_all_repositories()
    except KeyboardInterrupt:
        print("\n⏹️  Ingestion interrupted by user")
    except Exception as e:
        print(f"\n❌ Ingestion failed: {e}")
        raise


if __name__ == "__main__":
    main()
