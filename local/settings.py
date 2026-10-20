"""Local-only endpoints and PUBLIC emulator credentials; never use in Azure."""

EVENTHUB = "match-events"
EVENTHUB_CONNECTION = (
    "Endpoint=sb://eventhubs;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
SERVICEBUS_CONNECTION = EVENTHUB_CONNECTION.replace("eventhubs", "servicebus")
COSMOS_ENDPOINT = "http://cosmos:8081/"
# Microsoft's documented public emulator key, not an account credential.
COSMOS_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
POSTGRES_DSN = "host=postgres user=itg password=local-development-only"
SQL_PASSWORD = "Local-Only-Password-42!"
GRAPHQL = "http://graphql:5000/graphql"
