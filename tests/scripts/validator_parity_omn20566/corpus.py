# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fixture corpus for the OMN-20566 verdict-parity tests.

Each rule has a mapping ``case name -> {repo-relative path: source}``. A case is
one throwaway repository. The cases are the old scripts' own unit-test inputs
(``tests/unit/test_ci_enforcement_checks.py``, ``tests/unit/scripts/``) plus the
branches the scripts' source shows, so a conversion that loses a finding shows
up as a case whose verdict moved.

Fixture lines that carry a forbidden literal are data for the validators, not
code of this repository.
"""

from __future__ import annotations

from collections.abc import Mapping

Case = Mapping[str, str]

# Internal-address literals and the suppression markers the validators honour are
# spelled as tokens and substituted when a case is written to disk. They are data
# for the validators under test; spelled out here they would count as this file's
# own suppression comments and addresses.
FIXTURE_TOKENS: dict[str, str] = {
    "IPTOK_192_A": "192." + "168.86.201",
    "IPTOK_192_B": "192." + "168.1.5",
    "IPTOK_192_C": "192." + "168.5.5",
    "IPTOK_192_D": "192." + "168.0.9",
    "IPTOK_192_E": "192." + "168.1.1",
    "IPTOK_10_A": "10." + "0.0.5",
    "IPTOK_10_B": "10." + "1.2.3",
    "IPTOK_10_C": "10." + "0.0.1",
    "IPTOK_172_A": "172." + "16.0.1",
    "IPTOK_172_B": "172." + "31.255.1",
    "IPTOK_172_C": "172." + "15.0.1",
    "IPTOK_172_D": "172." + "32.0.1",
    "IPTOK_172_E": "172." + "20.1.1",
    "MARKTOK_DI_OK": "# di" + "-ok",
    "MARKTOK_FALLBACK_OK": "# fallback" + "-ok",
    "MARKTOK_CLOUD_BUS_OK": "# cloud-bus" + "-ok",
    "MARKTOK_IP_OK": "# onex" + "-allow-internal-ip",
}

_CLEAN_PY = "def now() -> int:\n    return 1\n"

# ---------------------------------------------------------------------------
# no_utcnow
# ---------------------------------------------------------------------------
UTCNOW: dict[str, Case] = {
    "clean": {
        "src/pkg/clean.py": (
            "from datetime import datetime, timezone\n\n"
            "def now():\n    return datetime.now(tz=timezone.utc)\n"
        ),
    },
    "datetime_utcnow": {
        "src/pkg/a.py": "from datetime import datetime\n\nx = datetime.utcnow()\n",
    },
    "dt_alias_utcnow": {
        "src/pkg/a.py": "import datetime as dt\n\nx = dt.utcnow()\n",
    },
    "datetime_datetime_utcnow": {
        "src/pkg/a.py": "import datetime\n\nts = datetime.datetime.utcnow()\n",
    },
    "other_receiver_utcnow": {
        "src/pkg/a.py": "x = get_clock().utcnow()\n",
    },
    "bare_attribute_without_call": {
        "src/pkg/a.py": "from datetime import datetime\n\nf = datetime.utcnow\n",
    },
    "syntax_error": {
        "src/pkg/bad.py": "def (:\n",
    },
    "nested_and_mixed": {
        "src/pkg/sub/deep/clean.py": _CLEAN_PY,
        "src/pkg/sub/deep/dirty.py": (
            "import datetime\n\n\ndef f():\n    return datetime.datetime.utcnow()\n"
        ),
        "src/pkg/other.py": "from datetime import datetime\nx = datetime.utcnow()\n",
    },
    "out_of_scope_tests_dir": {
        "src/pkg/clean.py": _CLEAN_PY,
        "tests/test_x.py": "from datetime import datetime\nx = datetime.utcnow()\n",
    },
    "no_python_at_all": {
        "src/pkg/notes.md": "datetime.utcnow()\n",
    },
}

# ---------------------------------------------------------------------------
# no_hardcoded_ip
# ---------------------------------------------------------------------------
HARDCODED_IP: dict[str, Case] = {
    "clean": {
        "src/pkg/clean.py": 'URL = os.environ["ENDPOINT"]\n',
    },
    "private_192_py": {
        "src/pkg/a.py": 'URL = "http://IPTOK_192_A:8085"\n',
    },
    "private_10_yaml": {
        "src/pkg/a.yaml": "host: IPTOK_10_A\n",
    },
    "private_172_range_edges": {
        "src/pkg/a.py": 'A = "IPTOK_172_A"\nB = "IPTOK_172_B"\nC = "IPTOK_172_C"\nD = "IPTOK_172_D"\n',
    },
    "yml_suffix": {
        "src/pkg/a.yml": "bootstrap: IPTOK_192_E:9092\n",
    },
    "suppressed_by_marker": {
        "src/pkg/a.py": 'URL = "http://IPTOK_192_A:8085"  MARKTOK_IP_OK\n',
    },
    "marker_on_other_line_does_not_suppress": {
        "src/pkg/a.py": 'MARKTOK_IP_OK\nURL = "http://IPTOK_192_A:8085"\n',
    },
    "tests_and_scripts_dirs": {
        "tests/test_a.py": 'HOST = "IPTOK_10_B"\n',
        "scripts/run.py": 'HOST = "IPTOK_192_D"\n',
        "src/pkg/clean.py": _CLEAN_PY,
    },
    "multiple_per_file": {
        "src/pkg/a.py": 'A = "IPTOK_10_C"\nB = 1\nC = "IPTOK_192_C"\n',
        "src/pkg/b.yaml": "x: 1\ny: IPTOK_172_E\n",
    },
    "public_and_loopback_are_fine": {
        "src/pkg/a.py": 'A = "8.8.8.8"\nB = "127.0.0.1"\nC = "11.0.0.1"\n',
    },
    "python_file_outside_scan_dirs": {
        "other/a.py": 'A = "IPTOK_10_C"\n',
        "src/pkg/clean.py": _CLEAN_PY,
    },
}

# ---------------------------------------------------------------------------
# no_direct_kafka_producer
# ---------------------------------------------------------------------------
DIRECT_KAFKA_PRODUCER: dict[str, Case] = {
    "clean": {
        "src/pkg/clean.py": (
            "from omnimarket.nodes.node_emit_daemon.client import EmitClient\n"
        ),
    },
    "aiokafka_import": {
        "src/pkg/a.py": (
            "from aiokafka import AIOKafkaProducer\n\n"
            "async def send_msg():\n"
            '    producer = AIOKafkaProducer(bootstrap_servers="x")\n'
            "    await producer.start()\n"
        ),
    },
    "confluent_kafka_import": {
        "src/pkg/a.py": "from confluent_kafka import Producer\n",
    },
    "import_statement": {
        "src/pkg/a.py": "import aiokafka\nimport confluent_kafka as ck\n",
    },
    "kafka_attribute_access": {
        "src/pkg/a.py": (
            "import kafka\n\n"
            "def get_producer():\n"
            '    return kafka.KafkaProducer(bootstrap_servers="x")\n'
        ),
    },
    "bare_name_usage": {
        "src/pkg/a.py": "p = KafkaProducer()\n",
    },
    "allowed_by_filename": {
        "src/pkg/lib/kafka_publisher_base.py": "from aiokafka import AIOKafkaProducer\n",
        "src/pkg/lib/emit_client.py": "import confluent_kafka\n",
    },
    "allowed_by_parent_directory": {
        "src/pkg/publisher/helper.py": "from aiokafka import AIOKafkaProducer\n",
    },
    "allowed_name_is_substring_match": {
        "src/pkg/my_publisher_thing.py": "from aiokafka import AIOKafkaProducer\n",
    },
    "grandparent_directory_does_not_allow": {
        "src/pkg/publisher/inner/helper.py": "from aiokafka import AIOKafkaProducer\n",
    },
    "syntax_error": {
        "src/pkg/bad.py": "def (:\n",
    },
    "mixed_allowed_and_not": {
        "src/pkg/lib/embedded_publisher.py": "import aiokafka\n",
        "src/pkg/nodes/node_x.py": "import aiokafka\n",
    },
}

# ---------------------------------------------------------------------------
# no_raw_sqlite3
# ---------------------------------------------------------------------------
RAW_SQLITE3: dict[str, Case] = {
    "clean": {
        "src/omniclaude/clean.py": "import sqlite3\n\nTYPE = sqlite3.Connection\n",
    },
    "module_connect": {
        "src/omniclaude/a.py": 'import sqlite3\n\nconn = sqlite3.connect("x.db")\n',
    },
    "aliased_module_connect": {
        "src/omniclaude/a.py": 'import sqlite3 as sq\n\nconn = sq.connect("x.db")\n',
    },
    "from_import_connect": {
        "src/omniclaude/a.py": 'from sqlite3 import connect\n\nconn = connect("x.db")\n',
    },
    "from_import_connect_alias": {
        "src/omniclaude/a.py": (
            'from sqlite3 import connect as open_db\n\nconn = open_db("x.db")\n'
        ),
    },
    "plugins_dir_is_checked": {
        "plugins/onex/hooks/a.py": 'import sqlite3\nconn = sqlite3.connect("x.db")\n',
    },
    "adapter_file_is_allowed": {
        "src/omniclaude/db_adapter.py": 'import sqlite3\nconn = sqlite3.connect("x")\n',
    },
    "di_ok_same_line": {
        "src/omniclaude/a.py": (
            'import sqlite3\nconn = sqlite3.connect("x.db")  MARKTOK_DI_OK bootstrap\n'
        ),
    },
    "di_ok_preceding_line": {
        "src/omniclaude/a.py": (
            'import sqlite3\nMARKTOK_DI_OK bootstrap\nconn = sqlite3.connect("x.db")\n'
        ),
    },
    "di_ok_on_closing_line_of_multiline_call": {
        "src/omniclaude/a.py": (
            "import sqlite3\n"
            "conn = sqlite3.connect(\n"
            '    "x.db",\n'
            ")  MARKTOK_DI_OK bootstrap\n"
        ),
    },
    "di_ok_two_lines_away_does_not_suppress": {
        "src/omniclaude/a.py": (
            "import sqlite3\nMARKTOK_DI_OK bootstrap\n\nconn = sqlite3.connect('x.db')\n"
        ),
    },
    "outside_checked_dirs": {
        "src/other_pkg/a.py": 'import sqlite3\nconn = sqlite3.connect("x")\n',
        "scripts/a.py": 'import sqlite3\nconn = sqlite3.connect("x")\n',
    },
    "tests_dir_is_excluded": {
        "src/omniclaude/tests/test_a.py": (
            'import sqlite3\nconn = sqlite3.connect("x")\n'
        ),
        "plugins/onex/tests/test_a.py": 'import sqlite3\nconn = sqlite3.connect("x")\n',
    },
    "other_module_connect_is_fine": {
        "src/omniclaude/a.py": 'import socket\n\ns = socket.connect(("h", 1))\n',
    },
    "syntax_error": {
        "src/omniclaude/bad.py": "def (:\n",
    },
}

# ---------------------------------------------------------------------------
# no_env_fallbacks
# ---------------------------------------------------------------------------
ENV_FALLBACKS: dict[str, Case] = {
    "clean": {
        "src/pkg/clean.py": 'import os\n\nHOST = os.environ["HOST"]\n',
        "scripts/run.sh": 'echo "${HOST:?set HOST}"\n',
    },
    "environ_get_localhost": {
        "src/pkg/a.py": 'import os\nx = os.environ.get("H", "localhost:8080")\n',
    },
    "getenv_localhost": {
        "src/pkg/a.py": 'import os\nx = os.getenv("H", "http://localhost:8080")\n',
    },
    "pydantic_default_loopback": {
        "src/pkg/a.py": 'class C:\n    url = Field(default="http://127.0.0.1:9")\n',
    },
    "str_param_default": {
        "src/pkg/a.py": 'def f(host: str = "localhost"):\n    return host\n',
    },
    "environ_get_private_ip": {
        "src/pkg/a.py": 'import os\nx = os.environ.get("H", "IPTOK_192_B")\n',
    },
    "default_private_ip": {
        "src/pkg/a.py": 'class C:\n    h: str = "IPTOK_192_B"\n',
    },
    "bootstrap_servers_literal": {
        "src/pkg/a.py": 'p = Client(bootstrap_servers="localhost:9092")\n',
    },
    "shell_default_expansion": {
        "scripts/run.sh": 'HOST="${HOST:-localhost}"\n',
        "scripts/run2.bash": 'URL="${URL:-http://localhost:8080}"\nIP="${IP:-IPTOK_192_E}"\n',
    },
    "exempt_markers": {
        "src/pkg/a.py": (
            "import os\n"
            'a = os.getenv("H", "localhost")  MARKTOK_FALLBACK_OK: dev only\n'
            'b = os.getenv("H", "localhost")  MARKTOK_CLOUD_BUS_OK\n'
            'c = os.getenv("H", "localhost")  # OMN-7227-exempt\n'
        ),
        "scripts/run.sh": 'H="${H:-localhost}"  MARKTOK_FALLBACK_OK: x\n',
    },
    "pure_comment_lines_are_skipped": {
        "src/pkg/a.py": '# os.getenv("H", "localhost")\n',
        "scripts/run.sh": '# H="${H:-localhost}"\n',
    },
    "docstring_lines_are_skipped": {
        "src/pkg/a.py": (
            '"""\nExample: os.getenv("H", "localhost")\n"""\nx = 1\n'
            '"""one line os.getenv("H", "localhost")"""\ny = 2\n'
        ),
    },
    "executable_after_docstring_close": {
        "src/pkg/a.py": '"""doc""" ; x = os.getenv("H", "localhost")\n',
    },
    "embedded_triple_quotes_do_not_start_docstring": {
        "src/pkg/module.py": (
            'marker = """not a docstring opener"""\nurl = os.getenv("X", "localhost")\n'
        ),
    },
    "embedded_triple_quotes_on_fallback_line_still_scan": {
        "src/pkg/module.py": 'url = os.getenv("X", "localhost") + """suffix"""\n',
    },
    "skip_dirs_are_ignored": {
        "src/pkg/tests/test_a.py": 'x = os.getenv("H", "localhost")\n',
        "src/pkg/test/test_a.py": 'x = os.getenv("H", "localhost")\n',
        "src/pkg/node_tests/a.py": 'x = os.getenv("H", "localhost")\n',
        "src/pkg/__tests__/a.py": 'x = os.getenv("H", "localhost")\n',
        "src/pkg/venv/a.py": 'x = os.getenv("H", "localhost")\n',
    },
    "multiple_findings_and_files": {
        "src/pkg/a.py": (
            'import os\na = os.getenv("H", "localhost")\nb = 1\n'
            'c = os.environ.get("H", "127.0.0.1")\n'
        ),
        "src/pkg/b.py": 'x = os.getenv("H", "localhost")\n',
        "scripts/r.sh": 'A="${A:-localhost}"\n',
    },
    "unrelated_suffixes_are_ignored": {
        "src/pkg/a.yaml": "host: localhost\n",
        "src/pkg/a.md": 'os.getenv("H", "localhost")\n',
    },
    "outside_scan_roots": {
        "other/a.py": 'x = os.getenv("H", "localhost")\n',
        "src/pkg/clean.py": _CLEAN_PY,
    },
}

CORPUS: dict[str, dict[str, Case]] = {
    "no_utcnow": UTCNOW,
    "no_hardcoded_ip": HARDCODED_IP,
    "no_direct_kafka_producer": DIRECT_KAFKA_PRODUCER,
    "no_raw_sqlite3": RAW_SQLITE3,
    "no_env_fallbacks": ENV_FALLBACKS,
}
