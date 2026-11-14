package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.concurrent.CompletionStage;

/** Narrow UI bridge. IDs refer only to the app's virtual library, never filesystem paths. */
public interface AssistantLibraryUi {
    JsonObject viewContext() throws Exception;
    CompletionStage<JsonObject> navigateFolder(String folderId);
    CompletionStage<JsonObject> openDocument(String documentId);
    /** Capture a bounded visual before the storage transaction; no persistent mutation. */
    Object prepareMutation(JsonArray changes) throws Exception;
    /** Release transient captures when validation or the storage commit is rejected. */
    default void cancelMutation(Object prepared) {}
    /** Reload committed virtual locations and reuse the existing drop animation. */
    CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result);
}
