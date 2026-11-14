package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.*;

/** Catalog and transactions for the in-app virtual library, never arbitrary OS paths. */
final class AssistantLibrary {
    private final Path root;
    AssistantLibrary(){this(PdfLibraryStore.defaultRoot());}
    AssistantLibrary(Path root){this.root=root.toAbsolutePath().normalize();}
    Path root(){return root;}

    JsonObject snapshot() throws IOException {
        PdfLibraryOrganization organization=PdfLibraryOrganization.load(root);
        List<JsonObject> rows=new ArrayList<>();
        for(var folder:organization.folders()){
            JsonObject row=row("folder",folder.id(),folder.name(),folder.parentId(),organization);
            row.addProperty("path",organization.displayPath(folder.id()));row.addProperty("systemTrash",PdfLibraryOrganization.isTrash(folder.id()));
            row.addProperty("trashed",!PdfLibraryOrganization.isTrash(folder.id())&&organization.isFolderInTrash(folder.id()));rows.add(row);
        }
        for(var document:PdfLibraryStore.list(root)){
            JsonObject row=row("document",document.id(),document.name(),organization.location(document.id()),organization);
            row.addProperty("trashed",organization.isDocumentInTrash(document.id()));rows.add(row);
        }
        rows.sort(Comparator.comparing((JsonObject row)->row.get("path").getAsString()).thenComparing(row->row.get("kind").getAsString()).thenComparing(row->row.get("id").getAsString()));
        JsonArray items=new JsonArray();rows.forEach(items::add);
        JsonObject result=new JsonObject();result.addProperty("revision",PdfLibraryOrganization.sha256((organization.revision()+"\n"+items).getBytes(StandardCharsets.UTF_8)));
        result.addProperty("organizationRevision",organization.revision());result.addProperty("rootId","");result.addProperty("rootPath","홈화면");result.add("items",items);result.addProperty("total",items.size());return result;
    }
    private static JsonObject row(String kind,String id,String name,String parent,PdfLibraryOrganization organization){
        JsonObject result=new JsonObject();result.addProperty("kind",kind);result.addProperty("id",id);result.addProperty("name",name);result.addProperty("parentId",parent);
        String parentPath=organization.displayPath(parent);result.addProperty("parentPath",parentPath);result.addProperty("path",parentPath+" > "+name);
        JsonArray ancestry=new JsonArray();ancestry.add("");for(var folder:organization.path(parent))ancestry.add(folder.id());result.add("ancestorIds",ancestry);return result;
    }

    /** Omitted/null parent means the entire tree; empty parent ID means the home root only. */
    JsonObject query(JsonObject args) throws IOException {
        keys(args,Set.of("query","kind","parentId","offset","limit","expectedRevision"));
        String query=text(args,"query","",200).strip(),kind=text(args,"kind","all",20);
        if(!Set.of("all","folder","document").contains(kind))throw new IOException("조회할 항목 종류를 확인해 주세요.");
        String parent=args.has("parentId")&&!args.get("parentId").isJsonNull()?text(args,"parentId","",128):null;
        int offset=integer(args,"offset",0,0,100000),limit=integer(args,"limit",60,1,100);
        JsonObject catalog=snapshot();String revision=catalog.get("revision").getAsString();
        if(offset>0&&(!args.has("expectedRevision")||!revision.equals(text(args,"expectedRevision","",64))))throw new IOException("목록이 변경됐거나 조회 버전이 없어요. 첫 페이지부터 다시 조회해 주세요.");
        if(args.has("expectedRevision")&&!revision.equals(text(args,"expectedRevision","",64)))throw new IOException("파일 또는 폴더 목록이 변경됐어요. 다시 조회해 주세요.");
        if(parent!=null&&!parent.isEmpty()&&find(catalog,"folder",parent)==null)throw new IOException("조회할 폴더가 존재하지 않아요.");
        List<JsonObject> matches=new ArrayList<>();int exact=0;String normalized=normalize(query);
        for(JsonElement element:catalog.getAsJsonArray("items")){
            JsonObject item=element.getAsJsonObject();
            if(parent==null&&item.has("trashed")&&item.get("trashed").getAsBoolean())continue;
            if(!kind.equals("all")&&!item.get("kind").getAsString().equals(kind)||parent!=null&&!item.get("parentId").getAsString().equals(parent))continue;
            String name=normalize(item.get("name").getAsString());boolean exactMatch=!normalized.isEmpty()&&name.equals(normalized);
            boolean partial=name.contains(normalized)||normalized.contains(name);
            boolean similar=!normalized.isEmpty()&&!exactMatch&&!partial&&item.get("kind").getAsString().equals("folder")&&similarFolderName(normalized,name);
            if(!normalized.isEmpty()&&!exactMatch&&!partial&&!similar)continue;
            JsonObject match=item.deepCopy();match.addProperty("exactMatch",exactMatch);match.addProperty("matchQuality",normalized.isEmpty()?"all":exactMatch?"exact":partial?"partial":"similar");matches.add(match);if(exactMatch)exact++;
        }
        matches.sort(Comparator.comparingInt((JsonObject item)->switch(item.get("matchQuality").getAsString()){case "exact"->0;case "partial"->1;case "similar"->2;default->3;}).thenComparing(item->item.get("path").getAsString()).thenComparing(item->item.get("id").getAsString()));
        JsonArray page=new JsonArray();for(int i=offset;i<matches.size()&&page.size()<limit;i++)page.add(matches.get(i));
        JsonObject result=new JsonObject();result.addProperty("revision",revision);result.addProperty("rootId","");result.addProperty("rootPath","홈화면");result.addProperty("total",matches.size());result.addProperty("exactMatches",exact);result.add("items",page);result.addProperty("hasMore",offset+page.size()<matches.size());result.addProperty("nextOffset",offset+page.size());return result;
    }
    static JsonObject find(JsonObject snapshot,String kind,String id){for(JsonElement element:snapshot.getAsJsonArray("items")){JsonObject item=element.getAsJsonObject();if(item.get("kind").getAsString().equals(kind)&&item.get("id").getAsString().equals(id))return item;}return null;}
    static String normalize(String value){return java.text.Normalizer.normalize(value,java.text.Normalizer.Form.NFC).strip().toLowerCase(Locale.ROOT).replaceFirst("\\.pdf$","").replaceAll("\\s+","");}

    /** Bounded O(200) spelling/word-insertion suggestions for folder choices only. */
    private static boolean similarFolderName(String query,String name){
        if(query.length()<3||name.length()<3||query.length()>200||name.length()>200)return false;
        String shorter=query.length()<=name.length()?query:name,longer=query.length()<=name.length()?name:query;
        if(shorter.length()*2>=longer.length()){
            int at=0;for(int i=0;i<longer.length()&&at<shorter.length();i++)if(longer.charAt(i)==shorter.charAt(at))at++;
            if(at==shorter.length())return true;
        }
        Set<String> left=new HashSet<>(),right=new HashSet<>();
        for(int i=0;i+1<query.length();i++)left.add(query.substring(i,i+2));
        for(int i=0;i+1<name.length();i++)right.add(name.substring(i,i+2));
        int intersection=0;for(String pair:left)if(right.contains(pair))intersection++;
        return intersection*2>=left.size()+right.size()-intersection;
    }

    boolean hasOperation(String id)throws IOException{return PdfLibraryOrganization.load(root).hasAssistantOperation(id);}
    JsonObject undoInfo()throws IOException{return PdfLibraryOrganization.load(root).assistantUndoInfo();}
    JsonObject undo(String operationId,String target)throws IOException{JsonObject result=PdfLibraryOrganization.load(root).undoAssistant(operationId,target);result.add("revision",snapshot().get("revision"));return result;}
    JsonObject apply(String operationId,String expectedRevision,JsonArray changes) throws IOException {return apply(operationId,expectedRevision,changes,null);}
    JsonObject apply(String operationId,String expectedRevision,JsonArray changes,JsonObject context) throws IOException {
        PdfLibraryOrganization organization=PdfLibraryOrganization.load(root);
        // Durable receipts must still win over stale query revisions on a transport retry.
        if(organization.hasAssistantOperation(operationId)){
            JsonObject result=organization.applyAssistant(operationId,organization.revision(),changes);result.add("revision",snapshot().get("revision"));return result;
        }
        JsonObject catalog=snapshot();
        if(!catalog.get("revision").getAsString().equals(expectedRevision))throw new IOException("파일 또는 폴더 목록이 변경됐어요. 다시 조회해 주세요.");
        JsonObject result=organization.applyAssistant(operationId,catalog.get("organizationRevision").getAsString(),expectedRevision,changes,context);
        JsonElement committed=result.remove("catalogRevision");result.add("revision",committed!=null?committed:snapshot().get("revision"));return result;
    }
    private static void keys(JsonObject value,Set<String> allowed)throws IOException{for(String key:value.keySet())if(!allowed.contains(key))throw new IOException("허용되지 않은 파일 조회 필드예요.");}
    private static String text(JsonObject object,String key,String fallback,int maximum)throws IOException{JsonElement value=object.get(key);if(value==null||value.isJsonNull())return fallback;if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isString()||value.getAsString().length()>maximum)throw new IOException(key+" 값을 확인해 주세요.");return value.getAsString();}
    private static int integer(JsonObject object,String key,int fallback,int minimum,int maximum)throws IOException{JsonElement value=object.get(key);if(value==null)return fallback;try{if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isNumber())throw new NumberFormatException();int number=value.getAsBigDecimal().intValueExact();if(number<minimum||number>maximum)throw new NumberFormatException();return number;}catch(RuntimeException failure){throw new IOException(key+" 범위를 확인해 주세요.");}}
}
