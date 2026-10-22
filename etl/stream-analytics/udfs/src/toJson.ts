import type { Json } from "./types";

// The original message as JSON, without fields Stream Analytics adds on input.
function main(message: Json): string {
    var copy: Json = {};
    for (var key in message) {
        if (["EventProcessedUtcTime", "PartitionId", "EventEnqueuedUtcTime"].indexOf(key) < 0) copy[key] = message[key];
    }
    return JSON.stringify(copy);
}
