// GENERATED from src/toJson.ts by build.ts. Do not edit; edit the .ts and run `node build.ts`.
// The original message as JSON, without fields Stream Analytics adds on input.
function main(message) {
    var copy = {};
    for (var key in message) {
        if (["EventProcessedUtcTime", "PartitionId", "EventEnqueuedUtcTime"].indexOf(key) < 0)
            copy[key] = message[key];
    }
    return JSON.stringify(copy);
}
