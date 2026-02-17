import pathlib
import shutil
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture
def js_runtime(tmp_path: pathlib.Path) -> str:
    """Provide a JS runtime with pyodide installed in tmp.

    Why:
        The Pyodide test needs a JS runtime with the pyodide npm package.
        Node.js is preferred, but if unavailable, bun is used (or installed
        on the fly since it's a single ~13MB download). Pyodide is installed
        into tmp_path so node_modules never touches the repo.

    Returns:
        Absolute path to the JS runtime binary.
    """
    node = shutil.which("node")
    if node is not None:
        # On Windows, npm is a .cmd batch script that requires shell=True
        shell = sys.platform == "win32"
        subprocess.run(
            ["npm", "init", "-y"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=30,
            shell=shell,
        )
        subprocess.run(
            ["npm", "install", "pyodide"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=120,
            shell=shell,
        )
        return node

    bun = shutil.which("bun")
    if bun is None:
        # Install bun into tmp
        bun_dir = tmp_path / "bun"
        subprocess.run(
            [
                "bash",
                "-c",
                f"curl -fsSL https://bun.sh/install | BUN_INSTALL={bun_dir} bash",
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        bun = str(bun_dir / "bin" / "bun")

    subprocess.run(
        [bun, "add", "pyodide"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=120,
    )
    return bun


def test_rendercv_installs_in_pyodide(tmp_path: pathlib.Path, js_runtime: str) -> None:
    # Build the wheel into tmp
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        timeout=60,
    )
    wheel = next((tmp_path / "dist").glob("rendercv-*-py3-none-any.whl"))

    script = tmp_path / "test.mjs"
    script.write_text(f"""\
import {{ loadPyodide }} from "pyodide";

async function main() {{
    const pyodide = await loadPyodide();
    await pyodide.loadPackage("micropip");

    await pyodide.runPythonAsync(`
import micropip

# Pre-install email-validator because micropip may not resolve
# pydantic[email] extras notation correctly
await micropip.install("email-validator")

# Install rendercv from the locally built wheel
await micropip.install("file://{wheel.resolve()}")

# Verify import works
import rendercv
    `);
}}

main().catch(err => {{
    console.error(err.message);
    process.exit(1);
}});
""")

    # Run test
    result = subprocess.run(
        [js_runtime, str(script)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, f"Pyodide install failed:\n{result.stderr}"
