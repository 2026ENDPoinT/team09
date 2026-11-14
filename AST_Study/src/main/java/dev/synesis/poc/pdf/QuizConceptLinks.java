package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;

/** Resolves saved quiz metadata against existing concept cards, without inference or I/O. */
final class QuizConceptLinks {
    record Target(String documentId,int index,String title,String identity) {}
    private static final Pattern SOURCE=Pattern.compile("^study:(c[1-9][0-9]*):e[1-9][0-9]*$");
    private QuizConceptLinks() {}

    static List<Target> resolve(QuizQuestion question,JsonObject study) {
        if(question.preview()||!question.documentId().equals(text(study,"documentId")))return List.of();
        List<JsonObject> concepts=concepts(study);
        List<String> ids=new ArrayList<>(question.conceptIds());
        if(ids.isEmpty())for(var evidence:question.evidence()) {
            var match=SOURCE.matcher(evidence.sourceId());
            if(match.matches()&&!ids.contains(match.group(1)))ids.add(match.group(1));
        }
        List<Target> direct=new ArrayList<>();
        for(String id:ids) {
            int index;
            try {index=Integer.parseInt(id.substring(1))-1;}
            catch(RuntimeException invalid){direct.clear();break;}
            if(index<0||index>=concepts.size()||text(concepts.get(index),"name").isBlank()){direct.clear();break;}
            direct.add(target(question.documentId(),index,concepts.get(index)));
        }
        // cN is positional. Check saved names too, so reordered concepts cannot
        // silently redirect an old question to a different concept.
        if(!direct.isEmpty()&&String.join(" · ",direct.stream().map(Target::title).toList()).equals(question.concept().strip()))
            return List.copyOf(direct);

        List<Target> whole=uniqueTitles(question.documentId(),List.of(question.concept().strip()),concepts);
        if(!whole.isEmpty())return whole;
        return uniqueTitles(question.documentId(),Arrays.asList(question.concept().split(" · ",-1)),concepts);
    }

    static int find(Target target,JsonObject study) {
        if(!target.documentId().equals(text(study,"documentId")))return -1;
        List<JsonObject> concepts=concepts(study);
        if(target.index()>=0&&target.index()<concepts.size()
                &&identity(concepts.get(target.index())).equals(target.identity()))return target.index();
        int found=-1;
        for(int i=0;i<concepts.size();i++)if(identity(concepts.get(i)).equals(target.identity())) {
            if(found>=0)return -1;
            found=i;
        }
        return found;
    }

    private static List<Target> uniqueTitles(String documentId,List<String> names,List<JsonObject> concepts) {
        List<Target> result=new ArrayList<>();Set<Integer> used=new HashSet<>();
        for(String name:names) {
            if(name.isBlank())return List.of();
            int found=-1;
            for(int i=0;i<concepts.size();i++)if(text(concepts.get(i),"name").equals(name)) {
                if(found>=0)return List.of();
                found=i;
            }
            if(found<0)return List.of();
            if(used.add(found))result.add(target(documentId,found,concepts.get(found)));
        }
        return List.copyOf(result);
    }

    private static Target target(String documentId,int index,JsonObject concept) {
        return new Target(documentId,index,text(concept,"name"),identity(concept));
    }
    private static String identity(JsonObject concept) {
        return UUID.nameUUIDFromBytes(concept.toString().getBytes(StandardCharsets.UTF_8)).toString();
    }
    private static List<JsonObject> concepts(JsonObject study) {
        if(study==null||!study.has("concepts")||!study.get("concepts").isJsonArray())return List.of();
        List<JsonObject> result=new ArrayList<>();
        // Preserve source positions, including damaged entries, for cN mapping.
        for(JsonElement item:study.getAsJsonArray("concepts"))result.add(item.isJsonObject()?item.getAsJsonObject():new JsonObject());
        return result;
    }
    private static String text(JsonObject value,String key) {
        JsonElement field=value==null?null:value.get(key);
        return field!=null&&field.isJsonPrimitive()&&field.getAsJsonPrimitive().isString()?field.getAsString().strip():"";
    }
}
