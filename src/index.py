from src.config.env import env


def main() -> None:
    print("Transit Buddy project initialized successfully.")
    print("Initialization mode: Discord, MongoDB, and LangChain integrations are not yet active.")
    print(f"Environment: {env.get('NODE_ENV', 'development')}")


if __name__ == "__main__":
    main()
