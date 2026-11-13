"""Internal worker for imports; stdout contains only the bounded JSON result."""

import json
import sys

from hatelens.social import FetchProblem, fetch_x, fetch_youtube


def main():
    try:
        request = json.load(sys.stdin)
        if request["target"]["source"] == "YouTube":
            data = fetch_youtube(request["target"], request["limit"], request["sort"], request["include_replies"])
        else:
            data = fetch_x(request["target"], request["limit"], request["token"])
        result = {"ok": True, "data": data}
    except FetchProblem as error:
        result = {"ok": False, "message": str(error), "status": error.status}
    except Exception:
        result = {"ok": False, "message": "The provider could not read these comments. Try again or upload an export.", "status": 502}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
