package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.StandardOpenOption;
import java.nio.channels.FileChannel;
import java.security.MessageDigest;
import java.util.concurrent.ConcurrentHashMap;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;
import java.util.UUID;

/** A virtual folder tree; PDF copies and generated data keep their original paths. */
final class PdfLibraryOrganization {
    record Folder(String id, String parentId, String name, String icon, String color) {}
    static final String DEFAULT_ICON="folder", DEFAULT_COLOR="#84203f";
    static final String TRASH_ID="synesis-trash";

    private static final Map<Path,Object> LOCKS=new ConcurrentHashMap<>();
    private final Path file;
    private String loadedRevision=sha256(new byte[0]);
    private JsonObject metadata=new JsonObject();
    private final List<Folder> folders = new ArrayList<>();
    private final Map<String,String> locations = new HashMap<>();

    private PdfLibraryOrganization(Path root) { file=root.toAbsolutePath().normalize().resolve("library-organization.json"); }

    static PdfLibraryOrganization load(Path root) throws IOException {
        PdfLibraryOrganization result=new PdfLibraryOrganization(root);
        if(!Files.isRegularFile(result.file))return result;
        try {
            byte[] bytes=Files.readAllBytes(result.file);
            JsonObject data=JsonParser.parseString(new String(bytes,StandardCharsets.UTF_8)).getAsJsonObject();
            result.loadedRevision=sha256(bytes);result.metadata=data.deepCopy();result.metadata.remove("folders");result.metadata.remove("documents");
            if(data.has("folders"))for(var entry:data.getAsJsonArray("folders")) {
                JsonObject folder=entry.getAsJsonObject();
                String id=folder.get("id").getAsString();
                String parent=folder.get("parentId").getAsString();
                String name=folder.get("name").getAsString();
                String icon=folder.has("icon")?folder.get("icon").getAsString():DEFAULT_ICON;
                String color=folder.has("color")?folder.get("color").getAsString():DEFAULT_COLOR;
                if(!id.isBlank() && !name.isBlank())
                    result.folders.add(new Folder(id,parent,name,icon,color));
            }
            if(data.has("documents"))for(var entry:data.getAsJsonObject("documents").entrySet())
                result.locations.put(entry.getKey(),entry.getValue().getAsString());
        } catch(RuntimeException error) { throw new IOException("폴더 목록을 읽지 못했어요.",error); }
        return result;
    }

    String revision() {return loadedRevision;}
    boolean hasAssistantOperation(String id){return metadata.has("assistantOperations")&&metadata.getAsJsonObject("assistantOperations").has(id);}
    List<Folder> folders() { return List.copyOf(folders); }
    String location(String documentId) { return locations.getOrDefault(documentId,""); }
    static boolean isTrash(String id){return TRASH_ID.equals(id);}
    boolean isFolderInTrash(String id){return path(id).stream().anyMatch(folder->isTrash(folder.id()));}
    boolean isDocumentInTrash(String id){return isFolderInTrash(location(id));}

    Folder ensureTrashFolder() throws IOException {
        Folder existing=folder(TRASH_ID);if(existing!=null)return existing;
        String name="휴지통";int suffix=1;
        while(hasFolderName("",name))name="휴지통 (시스템"+(suffix++==1?"":" "+(suffix-1))+")";
        Folder trash=new Folder(TRASH_ID,"",name,"trash","#7546ff");folders.add(trash);
        try{save();}catch(IOException error){folders.remove(trash);throw error;}
        return trash;
    }
    private boolean hasFolderName(String parent,String name){return folders.stream().anyMatch(folder->folder.parentId().equals(parent)&&folder.name().equalsIgnoreCase(name));}
    private void requireEditableFolder(String id)throws IOException {
        if(isTrash(id))throw new IOException("휴지통 자체는 이동하거나 변경·삭제할 수 없어요.");
    }

    /** Virtual relocation only: keep PDFs, generated work, history and open tasks untouched. */
    void moveToTrash(List<String> documentIds,List<String> folderIds)throws IOException {
        for(String id:documentIds)if(id==null||!id.matches("[0-9a-f]{64}")
                ||!Files.isRegularFile(file.getParent().resolve(id).resolve("source.pdf")))throw new IOException("이동할 문서를 찾지 못했어요.");
        for(String id:folderIds){requiredFolder(id);requireEditableFolder(id);}
        ensureTrashFolder();
        List<Folder> previousFolders=new ArrayList<>(folders);Map<String,String> previousLocations=new HashMap<>(locations);
        Set<String> covered=new HashSet<>();for(String id:folderIds)covered.addAll(folderTreeIds(id));
        for(String id:folderIds){
            Folder folder=requiredFolder(id);
            if(isFolderInTrash(id)||folderIds.stream().anyMatch(parent->!parent.equals(id)&&path(id).stream().anyMatch(ancestor->ancestor.id().equals(parent))))continue;
            folders.set(folders.indexOf(folder),new Folder(id,TRASH_ID,folder.name(),folder.icon(),folder.color()));
        }
        for(String id:documentIds)if(!covered.contains(location(id))&&!isDocumentInTrash(id))locations.put(id,TRASH_ID);
        try{save();}catch(IOException error){folders.clear();folders.addAll(previousFolders);locations.clear();locations.putAll(previousLocations);throw error;}
    }

    record RestoreResult(int restoredCount,int homeFallbackCount) {}

    /** Restore one validated selection atomically; never overwrite/delete existing material. */
    RestoreResult restoreFromTrash(String expectedRevision,List<String> documentIds,List<String> folderIds)throws IOException {
        if(documentIds.isEmpty()&&folderIds.isEmpty())throw new IOException("복원할 항목을 선택해 주세요.");
        synchronized(LOCKS.computeIfAbsent(file,p->new Object())){
            Files.createDirectories(file.getParent());
            try(var channel=FileChannel.open(file.resolveSibling(file.getFileName()+".lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var lock=channel.lock()){
                PdfLibraryOrganization next=load(file.getParent());
                if(!next.revision().equals(expectedRevision))throw new IOException("선택한 항목이나 위치가 변경됐어요. 다시 확인해 주세요.");
                Set<String> docs=new HashSet<>(documentIds),selected=new HashSet<>(folderIds),covered=new HashSet<>();
                for(String id:selected){
                    next.requireEditableFolder(id);next.requiredFolder(id);
                    if(!next.isFolderInTrash(id))throw new IOException("휴지통 안의 항목만 복원할 수 있어요.");
                    covered.addAll(next.folderTreeIds(id));
                }
                for(String id:docs)if(id==null||!id.matches("[0-9a-f]{64}")||!Files.isRegularFile(file.getParent().resolve(id).resolve("source.pdf"))||!next.isDocumentInTrash(id))throw new IOException("복원할 파일이나 위치를 다시 확인해 주세요.");
                List<String> roots=selected.stream().filter(id->next.path(id).stream().noneMatch(parent->!parent.id().equals(id)&&selected.contains(parent.id()))).sorted().toList();
                // Resolve all destinations against the original snapshot, independent of selection order.
                Map<String,String> folderParents=new HashMap<>(),documentParents=new HashMap<>();int fallback=0;
                for(String id:roots){
                    String parent=next.trashOrigin("folder",id);
                    if(!next.restoreDestinationAvailable(parent,covered)||next.folderTreeIds(id).contains(parent)){parent="";fallback++;}
                    folderParents.put(id,parent);
                }
                for(String id:docs){
                    if(covered.contains(next.location(id)))continue;
                    String parent=next.trashOrigin("document",id);
                    if(!next.restoreDestinationAvailable(parent,covered)){parent="";fallback++;}
                    documentParents.put(id,parent);
                }
                for(var entry:folderParents.entrySet()){
                    Folder old=next.requiredFolder(entry.getKey());next.folders.set(next.folders.indexOf(old),new Folder(old.id(),entry.getValue(),old.name(),old.icon(),old.color()));
                }
                for(var entry:documentParents.entrySet())if(entry.getValue().isEmpty())next.locations.remove(entry.getKey());else next.locations.put(entry.getKey(),entry.getValue());
                next.validateTree();
                for(String id:roots){Folder folder=next.requiredFolder(id);next.requireUniqueName(id,folder.parentId(),folder.name());if(next.isFolderInTrash(id))throw new IOException("복원할 폴더의 원래 위치를 다시 확인해 주세요.");}
                for(String id:docs)if(next.isDocumentInTrash(id))throw new IOException("복원할 파일의 원래 위치를 다시 확인해 주세요.");
                next.writeLocked();copyFrom(next);return new RestoreResult(docs.size()+selected.size(),fallback);
            }
        }
    }
    private boolean restoreDestinationAvailable(String parent,Set<String> restoringFolders){
        return parent!=null&&(parent.isEmpty()||folder(parent)!=null&&!isTrash(parent)&&(!isFolderInTrash(parent)||restoringFolders.contains(parent)));
    }
    private String trashOrigin(String kind,String id){
        String key=kind+":"+id;JsonObject origins=metadata.has("trashOrigins")?metadata.getAsJsonObject("trashOrigins"):new JsonObject();
        if(origins.has(key))return origins.get(key).getAsString();
        // Earlier assistant moves already have durable source locations; reuse them for old trash items.
        if(metadata.has("assistantOperations")){
            List<JsonElement> receipts=new ArrayList<>(metadata.getAsJsonObject("assistantOperations").asMap().values());
            for(int i=receipts.size()-1;i>=0;i--){JsonObject receipt=receipts.get(i).getAsJsonObject();
                if(!receipt.has("moved"))continue;
                JsonArray moves=receipt.getAsJsonArray("moved");
                for(int j=moves.size()-1;j>=0;j--){JsonObject move=moves.get(j).getAsJsonObject();
                    if(kind.equals(move.get("kind").getAsString())&&id.equals(move.get("id").getAsString())&&isTrash(move.get("parentId").getAsString())&&move.has("sourceParentId"))return move.get("sourceParentId").getAsString();
                }
            }
        }
        return null;
    }
    /** Persist only IDs/parent IDs on entering trash, including descendants. No PDF reads/copies. */
    private JsonObject trashOriginsForSave()throws IOException {
        PdfLibraryOrganization before=load(file.getParent());
        JsonObject origins=metadata.has("trashOrigins")?metadata.getAsJsonObject("trashOrigins").deepCopy():new JsonObject();
        Set<String> folderIds=new HashSet<>(),documentIds=new HashSet<>(before.locations.keySet());documentIds.addAll(locations.keySet());
        before.folders.forEach(folder->folderIds.add(folder.id()));folders.forEach(folder->folderIds.add(folder.id()));
        for(String key:new ArrayList<>(origins.keySet()))if(key.startsWith("document:"))documentIds.add(key.substring(9));else if(key.startsWith("folder:"))folderIds.add(key.substring(7));
        for(String id:folderIds){
            String key="folder:"+id;Folder now=folder(id),old=before.folder(id);
            if(now==null||isTrash(id)||!isFolderInTrash(id))origins.remove(key);
            else if(old!=null&&!before.isFolderInTrash(id))origins.addProperty(key,old.parentId());
        }
        for(String id:documentIds){
            String key="document:"+id;
            if(!isDocumentInTrash(id))origins.remove(key);
            else if(!before.isDocumentInTrash(id))origins.addProperty(key,before.location(id));
        }
        return origins;
    }

    /** Delete only a confirmed, unchanged selection already inside the trash. */
    void permanentlyDeleteTrashed(String expectedRevision,List<String> documentIds,List<String> folderIds)throws IOException {
        synchronized(LOCKS.computeIfAbsent(file,p->new Object())){
            Files.createDirectories(file.getParent());
            try(var channel=FileChannel.open(file.resolveSibling(file.getFileName()+".lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var lock=channel.lock()){
                PdfLibraryOrganization next=load(file.getParent());
                if(!next.revision().equals(expectedRevision))throw new IOException("선택한 항목이나 위치가 변경됐어요. 다시 확인해 주세요.");
                Set<String> documents=new HashSet<>(documentIds),subtree=new HashSet<>();
                for(String id:folderIds){
                    next.requireEditableFolder(id);
                    if(!next.isFolderInTrash(id))throw new IOException("휴지통 안의 항목만 영구 삭제할 수 있어요.");
                    subtree.addAll(next.folderTreeIds(id));
                    if(!documents.containsAll(next.documentsInTree(id)))throw new IOException("폴더 내용이 변경됐어요. 다시 확인해 주세요.");
                }
                Map<String,PdfLibraryStore.Item> available=new HashMap<>();for(var item:PdfLibraryStore.list(file.getParent()))available.put(item.id(),item);
                for(String id:documents)if(!available.containsKey(id)||!next.isDocumentInTrash(id))throw new IOException("휴지통 안의 항목만 영구 삭제할 수 있어요.");
                for(String id:documents){
                    PdfUsageStore.archiveBeforeDelete(file.getParent(),available.get(id));
                    PdfLibraryStore.deleteFile(file.getParent(),id);next.locations.remove(id);
                    if(next.metadata.has("documentNames"))next.metadata.getAsJsonObject("documentNames").remove(id);
                }
                next.folders.removeIf(folder->subtree.contains(folder.id()));
                next.writeLocked();copyFrom(next);
            }
        }
    }
    String documentName(String id,String fallback){
        JsonObject names=metadata.has("documentNames")?metadata.getAsJsonObject("documentNames"):null;
        return names!=null&&names.has(id)?names.get(id).getAsString():fallback;
    }
    void renameDocument(String id,String name)throws IOException{
        if(id==null||!id.matches("[0-9a-f]{64}")||!Files.isRegularFile(file.getParent().resolve(id).resolve("source.pdf")))throw new IOException("문서를 찾지 못했어요.");
        String cleaned=name==null?"":name.strip();if(cleaned.isEmpty())throw new IOException("이름을 입력해 주세요.");
        JsonObject previous=metadata.deepCopy();
        JsonObject names=metadata.has("documentNames")?metadata.getAsJsonObject("documentNames"):new JsonObject();names.addProperty(id,cleaned);metadata.add("documentNames",names);
        try{save();}catch(IOException failure){metadata=previous;throw failure;}
    }

    Folder folder(String id) {
        for(Folder folder:folders)if(folder.id().equals(id))return folder;
        return null;
    }

    List<Folder> path(String id) {
        List<Folder> path=new ArrayList<>();
        for(int depth=0;!id.isBlank() && depth<=folders.size();depth++) {
            Folder folder=folder(id);
            if(folder==null)break;
            path.add(0,folder);
            id=folder.parentId();
        }
        return path;
    }

    Folder createFolder(String parentId,String name) throws IOException {
        String cleaned=name==null?"":name.strip();
        if(cleaned.isEmpty())throw new IOException("폴더 이름을 입력해 주세요.");
        if(!parentId.isEmpty() && folder(parentId)==null)throw new IOException("상위 폴더를 찾지 못했어요.");
        for(Folder sibling:folders)if(sibling.parentId().equals(parentId)
            && sibling.name().equalsIgnoreCase(cleaned))throw new IOException("같은 이름의 폴더가 이미 있어요.");
        Folder created=new Folder(UUID.randomUUID().toString(),parentId,cleaned,DEFAULT_ICON,DEFAULT_COLOR);
        folders.add(created);
        try { save(); } catch(IOException error) { folders.remove(created);throw error; }
        return created;
    }

    void moveDocument(String documentId,String folderId) throws IOException {
        moveDocuments(List.of(documentId),folderId);
    }

    /** Parallel file preparation must read and update placement under one lock. */
    static void placeImportedDocumentAtHome(Path root,String documentId) throws IOException {
        placeImportedDocument(root,documentId,"");
    }

    static void placeImportedDocument(Path root,String documentId,String destination) throws IOException {
        PdfLibraryOrganization store=new PdfLibraryOrganization(root);
        synchronized(LOCKS.computeIfAbsent(store.file,p->new Object())) {
            Files.createDirectories(store.file.getParent());
            try(var channel=FileChannel.open(store.file.resolveSibling(store.file.getFileName()+".lock"),
                    StandardOpenOption.CREATE,StandardOpenOption.WRITE);var held=channel.lock()) {
                PdfLibraryOrganization latest=load(root);
                if(!destination.isEmpty() && (latest.folder(destination)==null || latest.isFolderInTrash(destination)))
                    throw new IOException("선택한 폴더를 사용할 수 없어요. 위치를 다시 선택해 주세요.");
                if(latest.location(documentId).equals(destination))return;
                if(destination.isEmpty())latest.locations.remove(documentId);
                else latest.locations.put(documentId,destination);
                latest.writeLocked();
            }
        }
    }

    /** Validate the entire selection and persist once; a failed save rolls back every location. */
    void moveDocuments(List<String> documentIds,String folderId) throws IOException {
        if(documentIds.isEmpty())throw new IOException("이동할 문서를 선택해 주세요.");
        for(String id:documentIds)
            if(id==null || !id.matches("[0-9a-f]{64}"))throw new IOException("문서 식별자가 올바르지 않아요.");
        if(!folderId.isEmpty() && folder(folderId)==null)throw new IOException("대상 폴더를 찾지 못했어요.");
        Map<String,String> previous=new HashMap<>();
        for(String id:documentIds)previous.put(id,locations.get(id));
        for(String id:documentIds)
            if(folderId.isEmpty())locations.remove(id);else locations.put(id,folderId);
        try { save(); } catch(IOException error) {
            previous.forEach((id,location)->{if(location==null)locations.remove(id);else locations.put(id,location);});
            throw error;
        }
    }

    void forgetDocument(String documentId) throws IOException {
        String previous=locations.remove(documentId);
        JsonObject names=metadata.has("documentNames")?metadata.getAsJsonObject("documentNames"):null;
        JsonElement previousName=names==null?null:names.remove(documentId);
        if(previous==null&&previousName==null)return;
        try { save(); } catch(IOException error) {
            if(previous!=null)locations.put(documentId,previous);
            if(previousName!=null)names.add(documentId,previousName);
            throw error;
        }
    }

    void renameFolder(String id,String name) throws IOException {
        requireEditableFolder(id);
        Folder previous=requiredFolder(id);
        String cleaned=name==null?"":name.strip();
        if(cleaned.isEmpty())throw new IOException("폴더 이름을 입력해 주세요.");
        for(Folder sibling:folders)if(!sibling.id().equals(id)
            && sibling.parentId().equals(previous.parentId())
            && sibling.name().equalsIgnoreCase(cleaned))
            throw new IOException("같은 이름의 폴더가 이미 있어요.");
        replace(previous,new Folder(id,previous.parentId(),cleaned,previous.icon(),previous.color()));
    }

    void setIcon(String id,String icon) throws IOException {
        requireEditableFolder(id);
        Folder previous=requiredFolder(id);
        replace(previous,new Folder(id,previous.parentId(),previous.name(),icon,previous.color()));
    }

    void setColor(String id,String color) throws IOException {
        requireEditableFolder(id);
        Folder previous=requiredFolder(id);
        if(!color.matches("#[0-9a-fA-F]{6}"))throw new IOException("색상 값이 올바르지 않아요.");
        replace(previous,new Folder(id,previous.parentId(),previous.name(),previous.icon(),color));
    }

    void moveFolder(String id,String parentId) throws IOException {
        requireEditableFolder(id);
        Folder previous=requiredFolder(id);
        if(!parentId.isEmpty())requiredFolder(parentId);
        if(folderTreeIds(id).contains(parentId))throw new IOException("폴더를 자기 자신이나 하위 폴더로 옮길 수 없어요.");
        for(Folder sibling:folders)if(!isTrash(parentId)&&!sibling.id().equals(id)
            && sibling.parentId().equals(parentId)
            && sibling.name().equalsIgnoreCase(previous.name()))
            throw new IOException("같은 이름의 폴더가 이미 있어요.");
        replace(previous,new Folder(id,parentId,previous.name(),previous.icon(),previous.color()));
    }

    Set<String> folderTreeIds(String id) throws IOException {
        requiredFolder(id);
        Set<String> result=new HashSet<>();
        result.add(id);
        boolean changed;
        do {
            changed=false;
            for(Folder folder:folders)if(result.contains(folder.parentId()))
                changed|=result.add(folder.id());
        } while(changed);
        return result;
    }

    Set<String> documentsInTree(String id) throws IOException {
        Set<String> subtree=folderTreeIds(id);
        Set<String> result=new HashSet<>();
        locations.forEach((document,location) -> {
            if(subtree.contains(location))result.add(document);
        });
        return result;
    }

    void removeFolderTree(String id) throws IOException {
        requireEditableFolder(id);
        Set<String> subtree=folderTreeIds(id);
        List<Folder> removed=folders.stream().filter(folder->subtree.contains(folder.id())).toList();
        Map<String,String> removedLocations=new HashMap<>();
        locations.forEach((document,location) -> {
            if(subtree.contains(location))removedLocations.put(document,location);
        });
        folders.removeAll(removed);
        removedLocations.keySet().forEach(locations::remove);
        try {save();} catch(IOException error) {
            folders.addAll(removed);locations.putAll(removedLocations);throw error;
        }
    }

    private Folder requiredFolder(String id) throws IOException {
        Folder folder=folder(id);
        if(folder==null)throw new IOException("폴더를 찾지 못했어요.");
        return folder;
    }

    private void replace(Folder previous,Folder updated) throws IOException {
        int index=folders.indexOf(previous);
        folders.set(index,updated);
        try {save();} catch(IOException error) {folders.set(index,previous);throw error;}
    }

    /** One atomic organization commit. The model never supplies a filesystem path. */
    JsonObject applyAssistant(String operationId,String expectedRevision,JsonArray changes) throws IOException {
        return applyAssistant(operationId,expectedRevision,null,changes,null);
    }
    JsonObject applyAssistant(String operationId,String expectedRevision,String expectedCatalogRevision,JsonArray changes) throws IOException {
        return applyAssistant(operationId,expectedRevision,expectedCatalogRevision,changes,null);
    }
    JsonObject applyAssistant(String operationId,String expectedRevision,String expectedCatalogRevision,JsonArray changes,JsonObject recoveryContext) throws IOException {
        if(operationId==null||!operationId.matches("[0-9a-f]{64}"))throw new IOException("작업 식별자를 확인해 주세요.");
        if(changes==null||changes.isEmpty()||changes.size()>100)throw new IOException("한 번에 1~100개 항목을 정리할 수 있어요.");
        synchronized(LOCKS.computeIfAbsent(file,p->new Object())){
            Files.createDirectories(file.getParent());
            try(var channel=FileChannel.open(file.resolveSibling(file.getFileName()+".lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var lock=channel.lock()){
                PdfLibraryOrganization next=load(file.getParent());
                JsonObject receipts=next.metadata.has("assistantOperations")?next.metadata.getAsJsonObject("assistantOperations"):new JsonObject();
                if(receipts.has(operationId)){
                    JsonObject result=receipts.getAsJsonObject(operationId).deepCopy();result.addProperty("revision",next.revision());result.addProperty("replayed",true);copyFrom(next);return result;
                }
                if(!next.revision().equals(expectedRevision))throw new IOException("파일 또는 폴더 위치가 변경됐어요. 다시 조회해 주세요.");
                if(receipts.size()>=10000)throw new IOException("파일 정리 작업 기록이 가득 찼어요.");
                List<PdfLibraryStore.Item> documentItems=PdfLibraryStore.list(file.getParent());
                Set<String> documents=new HashSet<>();for(var item:documentItems)documents.add(item.id());
                JsonObject beforeCatalog=new AssistantLibrary(file.getParent()).snapshot(),beforeState=next.stateSnapshot();String beforeSignature=stateSignature(next);
                JsonObject displayNames=new JsonObject();for(JsonElement item:beforeCatalog.getAsJsonArray("items")){JsonObject row=item.getAsJsonObject();if(row.get("kind").getAsString().equals("document"))displayNames.add(row.get("id").getAsString(),row.get("name"));}beforeState.add("displayNames",displayNames);
                JsonArray resolved=new JsonArray(),created=new JsonArray(),moved=new JsonArray(),renamed=new JsonArray();Map<String,String> references=new HashMap<>();Set<String> touched=new HashSet<>();
                int unchanged=0;
                int index=0;
                for(JsonElement entry:changes){
                    if(!entry.isJsonObject())throw new IOException("파일 정리 작업 형식을 확인해 주세요.");
                    JsonObject change=entry.getAsJsonObject();String operation=required(change,"operation",30);
                    if(operation.equals("createFolder")){
                        allowedKeys(change,Set.of("operation","parentId","name","ref"));
                        String parent=resolveParent(change,references);if(!parent.isEmpty())next.requiredFolder(parent);
                        String name=required(change,"name",200).strip();if(name.isEmpty())throw new IOException("폴더 이름을 입력해 주세요.");
                        next.requireUniqueName("",parent,name);
                        String id=UUID.nameUUIDFromBytes((operationId+":"+index).getBytes(StandardCharsets.UTF_8)).toString();
                        Folder folder=new Folder(id,parent,name,DEFAULT_ICON,DEFAULT_COLOR);next.folders.add(folder);
                        JsonObject result=new JsonObject();result.addProperty("id",id);result.addProperty("parentId",parent);result.addProperty("name",name);result.addProperty("path",next.displayPath(id));
                        if(change.has("ref")){String ref=required(change,"ref",80);if(!ref.matches("[A-Za-z][A-Za-z0-9_-]{0,79}")||references.putIfAbsent(ref,id)!=null)throw new IOException("새 폴더 참조 이름이 중복되거나 올바르지 않아요.");result.addProperty("ref",ref);}
                        created.add(result);JsonObject row=change.deepCopy();row.addProperty("id",id);row.addProperty("parentId",parent);resolved.add(row);
                    }else if(operation.equals("move")||operation.equals("trash")){
                        boolean trash=operation.equals("trash");
                        allowedKeys(change,trash?Set.of("operation","kind","id"):Set.of("operation","kind","id","parentId"));
                        String kind=required(change,"kind",20),id=required(change,"id",128),parent=trash?TRASH_ID:resolveParent(change,references);
                        if(trash){
                            JsonObject original=AssistantLibrary.find(beforeCatalog,kind,id);
                            if(original==null)throw new IOException("휴지통으로 옮길 항목을 찾지 못했어요.");
                            if(isTrash(id)||original.has("trashed")&&original.get("trashed").getAsBoolean())throw new IOException("휴지통 안의 항목은 직접 ‘영구 삭제하기’로 삭제해 주세요.");
                            // Parent+child selection preserves the subtree regardless of input order.
                            boolean covered=false;
                            for(JsonElement selected:changes){JsonObject ref=selected.getAsJsonObject();
                                if(!"trash".equals(required(ref,"operation",30))||!"folder".equals(required(ref,"kind",20)))continue;
                                if(original.getAsJsonArray("ancestorIds").contains(new JsonPrimitive(required(ref,"id",128))))covered=true;
                            }
                            if(covered){unchanged++;index++;continue;}
                            if(next.folder(TRASH_ID)==null){
                                String name="휴지통";int suffix=1;while(next.hasFolderName("",name))name="휴지통 (시스템 "+suffix+++")";
                                next.folders.add(new Folder(TRASH_ID,"",name,"trash","#7546ff"));
                            }
                        }
                        if(!parent.isEmpty())next.requiredFolder(parent);
                        if(!touched.add(kind+":"+id))throw new IOException("한 작업에서 같은 항목을 두 번 이동할 수 없어요.");
                        String from;
                        if(kind.equals("document")){
                            if(!documents.contains(id))throw new IOException("이동할 문서를 찾지 못했어요. 다시 조회해 주세요.");
                            from=next.location(id);if(parent.isEmpty())next.locations.remove(id);else next.locations.put(id,parent);
                        }else if(kind.equals("folder")){
                            next.requireEditableFolder(id);
                            Folder folder=next.requiredFolder(id);from=folder.parentId();
                            if(next.folderTreeIds(id).contains(parent))throw new IOException("폴더를 자기 자신이나 하위 폴더로 옮길 수 없어요.");
                            next.requireUniqueName(id,parent,folder.name());next.folders.set(next.folders.indexOf(folder),new Folder(id,parent,folder.name(),folder.icon(),folder.color()));
                        }else throw new IOException("문서나 폴더만 이동할 수 있어요.");
                        JsonObject row=change.deepCopy();row.addProperty("parentId",parent);row.addProperty("sourceParentId",from);resolved.add(row);
                        JsonObject move=new JsonObject();move.addProperty("kind",kind);move.addProperty("id",id);move.addProperty("sourceParentId",from);move.addProperty("parentId",parent);moved.add(move);
                    }else if(operation.equals("rename")){
                        allowedKeys(change,Set.of("operation","kind","id","name"));
                        String kind=required(change,"kind",20),id=required(change,"id",128),name=required(change,"name",200).strip();
                        if(!touched.add(kind+":"+id))throw new IOException("한 작업에서 같은 항목을 두 번 변경할 수 없어요.");
                        if(name.isEmpty()||name.equals(".")||name.equals("..")||name.matches("(?s).*[\\\\/\\p{Cntrl}].*"))throw new IOException("이름은 경로 구분자나 제어 문자 없이 입력해 주세요.");
                        JsonObject old=AssistantLibrary.find(beforeCatalog,kind,id);
                        if(old==null)throw new IOException("이름을 바꿀 파일 또는 폴더가 없어요.");
                        if(kind.equals("folder")){
                            next.requireEditableFolder(id);
                            Folder previous=next.requiredFolder(id);next.folders.set(next.folders.indexOf(previous),new Folder(id,previous.parentId(),name,previous.icon(),previous.color()));
                        }else if(kind.equals("document")&&documents.contains(id)){
                            JsonObject names=next.metadata.has("documentNames")?next.metadata.getAsJsonObject("documentNames"):new JsonObject();names.addProperty(id,name);next.metadata.add("documentNames",names);
                        }else throw new IOException("항목 종류를 확인해 주세요.");
                        JsonObject row=change.deepCopy();row.addProperty("name",name);row.addProperty("oldName",old.get("name").getAsString());row.addProperty("oldPath",old.get("path").getAsString());resolved.add(row);
                        if(name.equals(old.get("name").getAsString()))unchanged++;else renamed.add(row.deepCopy());
                    }else throw new IOException("지원하지 않는 파일 정리 작업이에요.");
                    index++;
                }
                next.validateTree();
                // Check the final state, so A→B / B→A swaps work in a single atomic commit.
                for(JsonElement entry:renamed){
                    JsonObject row=entry.getAsJsonObject();String kind=row.get("kind").getAsString(),id=row.get("id").getAsString(),name=AssistantLibrary.normalize(row.get("name").getAsString());
                    String parent=kind.equals("folder")?next.requiredFolder(id).parentId():next.location(id);
                    if(kind.equals("folder"))for(Folder sibling:next.folders){
                        if(!sibling.id().equals(id)&&sibling.parentId().equals(parent)&&AssistantLibrary.normalize(sibling.name()).equals(name))throw new IOException("같은 위치에 같은 이름의 폴더가 이미 있어요.");
                    }
                    if(kind.equals("document"))for(var sibling:documentItems){
                        if(!sibling.id().equals(id)&&next.location(sibling.id()).equals(parent)&&AssistantLibrary.normalize(next.documentName(sibling.id(),sibling.name())).equals(name))throw new IOException("같은 위치에 같은 이름의 파일이 이미 있어요.");
                    }
                    row.addProperty("path",next.displayPath(parent)+" > "+row.get("name").getAsString());
                }
                if(expectedCatalogRevision!=null&&!new AssistantLibrary(file.getParent()).snapshot().get("revision").getAsString().equals(expectedCatalogRevision))
                    throw new IOException("파일 목록이 작업 중 변경됐어요. 다시 조회해 주세요.");
                // Paths may change again later in the same transaction (e.g. move a newly-created parent).
                for(JsonElement entry:created){JsonObject folder=entry.getAsJsonObject();folder.addProperty("path",next.displayPath(folder.get("id").getAsString()));}
                JsonObject result=new JsonObject();result.addProperty("applied",true);result.addProperty("replayed",false);result.add("createdFolders",created);result.add("changes",resolved);result.add("moved",moved);result.add("renamed",renamed);result.addProperty("renamedCount",renamed.size());result.addProperty("unchangedCount",unchanged);
                // One bounded native snapshot, independent of durable retry receipts. Never expose it to the model.
                JsonObject undo=new JsonObject();undo.addProperty("id",operationId);undo.addProperty("at",recoveryContext!=null&&recoveryContext.has("at")?recoveryContext.get("at").getAsLong():System.currentTimeMillis());undo.addProperty("undone",false);
                JsonObject context=recoveryContext==null?new JsonObject():recoveryContext.deepCopy();context.remove("at");context.add("changes",resolved.deepCopy());undo.add("context",context);
                JsonObject prior=next.metadata.has("assistantUndo")?next.metadata.getAsJsonObject("assistantUndo"):null;
                // Several library commits of a single human request form one undoable activity.
                boolean sameTurn=prior!=null&&prior.has("context")&&context.has("turn")&&context.has("session")&&context.get("turn").equals(prior.getAsJsonObject("context").get("turn"))&&context.get("session").equals(prior.getAsJsonObject("context").get("session"))&&!prior.get("undone").getAsBoolean()&&prior.get("afterSignature").getAsString().equals(beforeSignature);
                if(sameTurn){beforeState=prior.getAsJsonObject("before").deepCopy();JsonArray combined=prior.getAsJsonObject("context").getAsJsonArray("changes").deepCopy();resolved.forEach(combined::add);context.add("changes",combined);}
                undo.add("before",beforeState);next.metadata.add("trashOrigins",next.trashOriginsForSave());undo.addProperty("afterSignature",stateSignature(next));next.metadata.add("assistantUndo",undo);
                receipts.add(operationId,result.deepCopy());next.metadata.add("assistantOperations",receipts);next.writeLocked();copyFrom(next);result.addProperty("revision",revision());
                // Capture this commit's catalog before releasing the mutation lock.
                // A later edit must not become the assistant's own revision head.
                result.add("catalogRevision",new AssistantLibrary(file.getParent()).snapshot().get("revision"));return result;
            }
        }
    }

    /** Latest activity is retained even when consumed/conflicted; never fall through to an older domain. */
    JsonObject assistantUndoInfo()throws IOException {
        if(!metadata.has("assistantUndo")){
            if(!metadata.has("assistantOperations")||metadata.getAsJsonObject("assistantOperations").isEmpty())return new JsonObject();
            JsonObject legacy=new JsonObject();legacy.addProperty("at",Files.getLastModifiedTime(file).toMillis());legacy.addProperty("available",false);legacy.addProperty("reason","legacy_library_activity");return legacy;
        }
        JsonObject record=metadata.getAsJsonObject("assistantUndo"),out=new JsonObject();for(String key:List.of("id","at","undone","context"))if(record.has(key))out.add(key,record.get(key).deepCopy());
        out.addProperty("available",!record.get("undone").getAsBoolean()&&record.get("afterSignature").getAsString().equals(stateSignature(this)));return out;
    }
    JsonObject undoAssistant(String operationId,String target)throws IOException {
        if(operationId==null||!operationId.matches("[0-9a-f]{64}"))throw new IOException("작업 식별자를 확인해 주세요.");
        synchronized(LOCKS.computeIfAbsent(file,p->new Object())){
            Files.createDirectories(file.getParent());
            try(var channel=FileChannel.open(file.resolveSibling(file.getFileName()+".lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var lock=channel.lock()){
                PdfLibraryOrganization next=load(file.getParent());JsonObject receipts=next.metadata.has("assistantOperations")?next.metadata.getAsJsonObject("assistantOperations"):new JsonObject();
                if(receipts.has(operationId)){JsonObject replay=receipts.getAsJsonObject(operationId).deepCopy();replay.addProperty("replayed",true);return replay;}
                JsonObject record=next.metadata.has("assistantUndo")?next.metadata.getAsJsonObject("assistantUndo"):null;
                if(record==null||!target.equals(record.get("id").getAsString())||record.get("undone").getAsBoolean())throw new IOException("직전 파일 작업은 이미 되돌렸거나 복원 기록이 없어요.");
                if(!record.get("afterSignature").getAsString().equals(stateSignature(next)))throw new IOException("파일 작업 이후 자료가 변경돼 자동으로 되돌리지 않았어요. 현재 자료를 보존했어요.");
                if(receipts.size()>=10000)throw new IOException("파일 작업 기록이 가득 찼어요.");
                JsonObject currentCatalog=new AssistantLibrary(file.getParent()).snapshot();next.restoreState(record.getAsJsonObject("before"));next.validateTree();
                JsonArray moved=new JsonArray(),renamed=new JsonArray();
                for(JsonElement entry:currentCatalog.getAsJsonArray("items")){
                    JsonObject old=entry.getAsJsonObject();String kind=old.get("kind").getAsString(),id=old.get("id").getAsString();Folder folder=next.folder(id);
                    if(kind.equals("folder")&&folder==null)continue;
                    String parent=kind.equals("folder")?folder.parentId():next.location(id),name=kind.equals("folder")?folder.name():record.getAsJsonObject("before").getAsJsonObject("displayNames").get(id).getAsString();
                    if(!parent.equals(old.get("parentId").getAsString())){JsonObject row=new JsonObject();row.addProperty("kind",kind);row.addProperty("id",id);row.add("sourceParentId",old.get("parentId"));row.addProperty("parentId",parent);moved.add(row);}
                    if(!name.equals(old.get("name").getAsString())){JsonObject row=new JsonObject();row.addProperty("kind",kind);row.addProperty("id",id);row.add("oldName",old.get("name"));row.addProperty("name",name);renamed.add(row);}
                }
                JsonObject result=new JsonObject();result.addProperty("undone",true);result.addProperty("domain","library");result.addProperty("replayed",false);result.add("moved",moved);result.add("renamed",renamed);result.addProperty("renamedCount",renamed.size());
                record.addProperty("undone",true);next.metadata.add("assistantUndo",record);receipts.add(operationId,result.deepCopy());next.metadata.add("assistantOperations",receipts);
                next.writeLocked(false);copyFrom(next);return result;
            }
        }
    }
    private JsonObject stateSnapshot(){
        JsonObject state=new JsonObject();JsonArray rows=new JsonArray();folders.stream().sorted(java.util.Comparator.comparing(Folder::id)).forEach(folder->{JsonObject row=new JsonObject();row.addProperty("id",folder.id());row.addProperty("parentId",folder.parentId());row.addProperty("name",folder.name());row.addProperty("icon",folder.icon());row.addProperty("color",folder.color());rows.add(row);});state.add("folders",rows);
        JsonObject docs=new JsonObject();locations.forEach(docs::addProperty);state.add("documents",docs);
        for(String key:List.of("documentNames","trashOrigins"))state.add(key,metadata.has(key)?metadata.getAsJsonObject(key).deepCopy():new JsonObject());return state;
    }
    private void restoreState(JsonObject state){
        folders.clear();for(JsonElement entry:state.getAsJsonArray("folders")){JsonObject row=entry.getAsJsonObject();folders.add(new Folder(row.get("id").getAsString(),row.get("parentId").getAsString(),row.get("name").getAsString(),row.get("icon").getAsString(),row.get("color").getAsString()));}
        locations.clear();state.getAsJsonObject("documents").entrySet().forEach(e->locations.put(e.getKey(),e.getValue().getAsString()));
        for(String key:List.of("documentNames","trashOrigins")){JsonObject value=state.getAsJsonObject(key);if(value.isEmpty())metadata.remove(key);else metadata.add(key,value.deepCopy());}
    }
    private static String stateSignature(PdfLibraryOrganization state)throws IOException {
        JsonObject snapshot=state.stateSnapshot();JsonArray ids=new JsonArray();List<String> sources=new ArrayList<>();
        if(Files.isDirectory(state.file.getParent()))try(var entries=Files.newDirectoryStream(state.file.getParent())){for(Path entry:entries){String id=entry.getFileName().toString();if(id.matches("[0-9a-f]{64}")&&Files.isRegularFile(entry.resolve("source.pdf"),java.nio.file.LinkOption.NOFOLLOW_LINKS))sources.add(id);}}
        sources.stream().sorted().forEach(ids::add);snapshot.add("sourceIds",ids);
        return sha256(canonicalState(snapshot).getBytes(StandardCharsets.UTF_8));
    }
    private static String canonicalState(JsonElement value){
        if(value.isJsonObject()){List<String> rows=new ArrayList<>();value.getAsJsonObject().entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(e->rows.add(new JsonPrimitive(e.getKey())+":"+canonicalState(e.getValue())));return "{"+String.join(",",rows)+"}";}
        if(value.isJsonArray()){List<String> rows=new ArrayList<>();value.getAsJsonArray().forEach(e->rows.add(canonicalState(e)));return "["+String.join(",",rows)+"]";}return value.toString();
    }

    String displayPath(String folderId){StringBuilder out=new StringBuilder("홈화면");for(Folder folder:path(folderId))out.append(" > ").append(folder.name());return out.toString();}
    private static String resolveParent(JsonObject change,Map<String,String> references) throws IOException {
        String parent=required(change,"parentId",128);
        if(parent.startsWith("@")){String id=references.get(parent.substring(1));if(id==null)throw new IOException("앞에서 생성한 폴더만 참조할 수 있어요.");return id;}
        return parent;
    }
    private static String required(JsonObject object,String key,int maximum) throws IOException {
        JsonElement value=object.get(key);if(value==null||!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isString()||value.getAsString().length()>maximum)throw new IOException(key+" 값을 확인해 주세요.");return value.getAsString();
    }
    private static void allowedKeys(JsonObject object,Set<String> allowed) throws IOException {for(String key:object.keySet())if(!allowed.contains(key))throw new IOException("허용되지 않은 파일 정리 필드예요.");}
    private void requireUniqueName(String id,String parent,String name) throws IOException {if(isTrash(parent))return;for(Folder sibling:folders)if(!sibling.id().equals(id)&&sibling.parentId().equals(parent)&&sibling.name().equalsIgnoreCase(name))throw new IOException("대상 위치에 같은 이름의 폴더가 이미 있어요.");}
    private void validateTree() throws IOException {
        Set<String> ids=new HashSet<>();for(Folder folder:folders)if(!ids.add(folder.id()))throw new IOException("폴더 식별자가 중복돼 있어요.");
        for(Folder folder:folders){Set<String> seen=new HashSet<>();String id=folder.id();while(!id.isEmpty()){if(!seen.add(id))throw new IOException("폴더 경로가 순환하고 있어요.");id=requiredFolder(id).parentId();}}
    }
    private void copyFrom(PdfLibraryOrganization other){folders.clear();folders.addAll(other.folders);locations.clear();locations.putAll(other.locations);loadedRevision=other.loadedRevision;metadata=other.metadata.deepCopy();}
    private void save() throws IOException {
        synchronized(LOCKS.computeIfAbsent(file,p->new Object())){
            Files.createDirectories(file.getParent());
            try(var channel=FileChannel.open(file.resolveSibling(file.getFileName()+".lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var lock=channel.lock()){
                String disk=Files.isRegularFile(file)?sha256(Files.readAllBytes(file)):sha256(new byte[0]);
                if(!loadedRevision.equals(disk))throw new IOException("다른 작업에서 폴더 구성이 변경됐어요. 새로고침 후 다시 시도해 주세요.");
                writeLocked();
            }
        }
    }
    private void writeLocked() throws IOException {writeLocked(true);}
    private void writeLocked(boolean trackOrigins) throws IOException {
        JsonObject data=metadata.deepCopy();JsonObject origins=trackOrigins?trashOriginsForSave():metadata.has("trashOrigins")?metadata.getAsJsonObject("trashOrigins"):new JsonObject();if(origins.isEmpty())data.remove("trashOrigins");else data.add("trashOrigins",origins);JsonArray folderList=new JsonArray();
        for(Folder folder:folders){JsonObject value=new JsonObject();value.addProperty("id",folder.id());value.addProperty("parentId",folder.parentId());value.addProperty("name",folder.name());value.addProperty("icon",folder.icon());value.addProperty("color",folder.color());folderList.add(value);}
        data.add("folders",folderList);JsonObject documents=new JsonObject();locations.forEach(documents::addProperty);data.add("documents",documents);
        byte[] bytes=data.toString().getBytes(StandardCharsets.UTF_8);Path temporary=Files.createTempFile(file.getParent(),"library-organization-",".tmp");
        try{
            Files.write(temporary,bytes);try(var out=FileChannel.open(temporary,StandardOpenOption.WRITE)){out.force(true);}
            try{Files.move(temporary,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}catch(AtomicMoveNotSupportedException unsupported){Files.move(temporary,file,StandardCopyOption.REPLACE_EXISTING);}
            loadedRevision=sha256(bytes);metadata=data.deepCopy();metadata.remove("folders");metadata.remove("documents");
        }finally{Files.deleteIfExists(temporary);}
    }
    static String sha256(byte[] bytes){try{return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
