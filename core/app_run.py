import sys
from pathlib import Path

import uvicorn

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    uvicorn.run("core.main:app", reload=False, loop="asyncio", port=8020, host="0.0.0.0")
