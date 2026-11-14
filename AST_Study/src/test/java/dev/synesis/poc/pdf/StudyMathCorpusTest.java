package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;

/** Render real saved learner fields through the app renderer, without API calls. */
public final class StudyMathCorpusTest {
    private static final Pattern FORMULA=Pattern.compile("(?s)\\$\\$(.+?)\\$\\$|\\\\\\((.+?)\\\\\\)|\\\\\\[(.+?)\\\\\\]");
    public static void main(String[] args) throws Exception {
        Path result=Path.of(args[0]), output=Path.of(args[1]);
        Files.createDirectories(output);
        var root=JsonParser.parseString(Files.readString(result)).getAsJsonObject();
        Set<String> formulas=new LinkedHashSet<>();
        StringBuilder document=new StringBuilder("<!doctype html><meta charset='utf-8'><title>ver.02 실제 렌더링 결과</title><style>body{max-width:900px;margin:48px auto;padding:0 24px;font:17px/1.8 system-ui;color:#182234;background:#f8fafc}article{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:24px;margin:20px 0;overflow:auto}h2{font-size:22px}summary{color:#3359c9;cursor:pointer}details{background:#f1f5ff;padding:16px;border-radius:8px}img{vertical-align:middle}small{color:#64748b}</style><h1>New개념Ver ver.02</h1><p>앱의 수식 렌더러로 표시한 검증 결과예요.</p>");
        int fields=0;
        for(var section:root.getAsJsonArray("sections")) for(var element:section.getAsJsonObject().getAsJsonArray("parts")) {
            var part=element.getAsJsonObject();
            document.append("<article><small>근거 p.").append(part.get("visualPages")).append("</small>");
            for(String key:new String[]{"title","body","easyExplanation"}) {
                String text=part.get(key).getAsString(); fields++;
                String rendered=StudyMarkdown.render(text,18);
                Matcher matcher=FORMULA.matcher(text);
                while(matcher.find()) formulas.add(matcher.group());
                if(key.equals("title")) document.append("<h2>").append(StudyMarkdown.renderInline(text,18)).append("</h2>");
                else if(key.equals("easyExplanation")) document.append("<details><summary>쉬운 설명 보기</summary>").append(rendered).append("</details>");
                else document.append(rendered);
            }
            document.append("</article>");
        }
        Files.writeString(output.resolve("rendered.html"),document.append("</body></html>").toString());
        java.util.List<String> failed=new ArrayList<>();
        for(String formula:formulas) {
            String html=StudyMarkdown.render(formula,18);
            String swing=StudyHtmlPane.prepareForSwing(html);
            if(!html.contains("<math ") || !swing.contains("synesis-math-")) failed.add(formula);
        }
        JsonObject audit=new JsonObject();audit.addProperty("fields",fields);audit.addProperty("formulas",formulas.size());
        audit.add("failed",new Gson().toJsonTree(failed));
        Files.writeString(output.resolve("render-audit.json"),new GsonBuilder().setPrettyPrinting().create().toJson(audit));
        System.out.println(audit);
        if(!failed.isEmpty()) throw new AssertionError("Formula rendering failures: "+failed);
        System.exit(0);
    }
}
