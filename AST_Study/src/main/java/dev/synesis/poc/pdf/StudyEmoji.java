package dev.synesis.poc.pdf;

import java.awt.Font;
import java.awt.GraphicsEnvironment;
import java.util.Set;
import java.util.regex.Pattern;
import javax.swing.text.AttributeSet;
import javax.swing.text.Element;
import javax.swing.text.html.HTML;
import javax.swing.text.html.InlineView;

/** Keep prose fonts intact; resolve only emoji graphemes through the platform emoji face. */
final class StudyEmoji {
    private static final Pattern TOKENS=Pattern.compile("<[^>]*>|[^<]+"),GRAPHEMES=Pattern.compile("\\X");
    private static final String MARKER="synesis-emoji";
    private static final String FAMILY=family();
    private static String family(){
        Set<String> installed=Set.of(GraphicsEnvironment.getLocalGraphicsEnvironment().getAvailableFontFamilyNames());
        for(String name:new String[]{"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji","Segoe UI Symbol"})if(installed.contains(name))return name;
        return Font.DIALOG;
    }
    private static boolean emoji(String text){
        return text.codePoints().anyMatch(cp->cp>=0x1f000&&cp<=0x1faff||cp>=0x2600&&cp<=0x27bf||cp==0xfe0f||cp==0x20e3);
    }
    static String decorate(String html){
        if(html==null||!emoji(html))return html;
        StringBuilder result=new StringBuilder();var tokens=TOKENS.matcher(html);boolean style=false;
        while(tokens.find()){
            String token=tokens.group();
            if(token.startsWith("<")){result.append(token);if(token.matches("(?is)<style\\b.*"))style=true;else if(token.matches("(?is)</style\\s*>"))style=false;continue;}
            if(style){result.append(token);continue;}
            var clusters=GRAPHEMES.matcher(token);
            while(clusters.find()){String cluster=clusters.group();if(emoji(cluster))result.append("<span class='").append(MARKER).append("'>").append(cluster).append("</span>");else result.append(cluster);}
        }
        return result.toString();
    }
    static boolean matches(Element element){
        return element.getAttributes().getAttribute(HTML.Tag.SPAN) instanceof AttributeSet span&&MARKER.equals(span.getAttribute(HTML.Attribute.CLASS));
    }
    static InlineView view(Element element){
        return new InlineView(element){
            @Override public Font getFont(){return new Font(FAMILY,Font.PLAIN,super.getFont().getSize());}
        };
    }
}
