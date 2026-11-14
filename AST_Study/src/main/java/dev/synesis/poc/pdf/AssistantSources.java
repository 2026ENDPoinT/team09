package dev.synesis.poc.pdf;

import java.net.URI;
import java.util.ArrayList;
import java.util.regex.Pattern;

/** Assistant-owned source footer; the shared study renderer still strips arbitrary links. */
final class AssistantSources {
    private static final String FOOTER="\n\n**출처**\n";
    private static final Pattern SOURCE=Pattern.compile("^- \\[(\\d)\\. (.*)\\]\\(<(https://[^\\s<>]+)>\\)$");
    private record Source(String number,String title,String url){}
    static String render(String markdown,int font,int width){
        int start=markdown.lastIndexOf(FOOTER);
        if(start<0)return StudyMarkdown.renderWithScrollableMath(markdown,font,false,width);
        var sources=new ArrayList<Source>();
        for(String line:markdown.substring(start+FOOTER.length()).split("\\n")){
            var match=SOURCE.matcher(line);
            if(!match.matches())continue;
            try{
                URI uri=URI.create(match.group(3));
                if(!"https".equals(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null)continue;
                String title=match.group(2).replace("\\[","[").replace("\\]","]").replace("\\\\","\\");
                sources.add(new Source(match.group(1),title,uri.toASCIIString()));
            }catch(IllegalArgumentException ignored){}
        }
        if(sources.isEmpty())return StudyMarkdown.renderWithScrollableMath(markdown,font,false,width);
        String html=StudyMarkdown.renderWithScrollableMath(markdown.substring(0,start),font,false,width);
        StringBuilder footer=new StringBuilder("<p><strong>출처</strong></p><ul>");
        for(Source source:sources){
            html=StudyMarkdown.linkProseReference(html,"["+source.number()+"]",source.url());
            footer.append("<li><a href='").append(escape(source.url())).append("'>")
                .append(source.number()).append(". ").append(escape(source.title())).append("</a></li>");
        }
        return html+footer.append("</ul>");
    }
    private static String escape(String value){return value.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("'","&#39;").replace("\"","&quot;");}
}
