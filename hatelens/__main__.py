import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run the local HateLens workspace.")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    uvicorn.run("hatelens.app:app", host="127.0.0.1", port=arguments.port)


if __name__ == "__main__":
    main()
