package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.ui.LibraryDesign;
import dev.synesis.poc.ui.SmoothScrollPane;
import javax.swing.*;
import java.awt.*;
import java.util.Locale;

/** Read-only plain text; stored preferences are never interpreted as HTML or code. */
final class AssistantPreferencesPanel extends JPanel {
    AssistantPreferencesPanel(AssistantLocal.PreferencesDebug debug,int width){
        super(new BorderLayout(0,10));setBackground(AssistantChatTheme.BACKGROUND);setBorder(BorderFactory.createEmptyBorder(14,14,14,14));
        JPanel header=new JPanel(new BorderLayout(0,8));header.setOpaque(false);
        JLabel title=new JLabel("사용자 맞춤 지침 · 디버그");title.setFont(LibraryDesign.medium(14));title.setForeground(AssistantChatTheme.TEXT);header.add(title,BorderLayout.NORTH);
        JTextArea metadata=plain("파일: "+debug.path()+"\n상태: "+(debug.exists()?"저장 파일 있음":"저장 파일 없음 · 아직 생성되지 않았어요"));metadata.setLineWrap(true);metadata.setWrapStyleWord(true);metadata.setFont(LibraryDesign.medium(10));metadata.setSize(width-28,Short.MAX_VALUE);header.add(metadata);add(header,BorderLayout.NORTH);
        JTabbedPane tabs=new JTabbedPane();tabs.setBackground(AssistantChatTheme.BACKGROUND);tabs.setForeground(AssistantChatTheme.TEXT);tabs.setFont(LibraryDesign.medium(11));
        tabs.addTab("파일 원문",code(debug.exists()?debug.raw():"(파일 없음)",width));
        String api=debug.personalization()==null?debug.error():new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(debug.personalization());
        tabs.addTab("API 전달용 값",code(api,width));
        if(debug.personalization()!=null)tabs.addTab("요약 (가공 표시)",code(describe(debug.personalization()),width));
        add(tabs);
        JTextArea hint=plain("파일 원문은 디스크에서 읽은 그대로예요. API 전달용 값은 같은 파일에서 구성한 localContext.personalization이며, 마지막 요청을 캡처한 값은 아니에요.");hint.setLineWrap(true);hint.setWrapStyleWord(true);hint.setFont(LibraryDesign.medium(10));hint.setForeground(AssistantChatTheme.MUTED);hint.setSize(width-28,Short.MAX_VALUE);add(hint,BorderLayout.SOUTH);
    }
    private static JTextArea plain(String value){
        JTextArea text=new JTextArea(value);text.setEditable(false);text.setFont(LibraryDesign.medium(12));text.setForeground(AssistantChatTheme.TEXT);text.setBackground(AssistantChatTheme.BACKGROUND);text.setCaretColor(AssistantChatTheme.TEXT);text.setBorder(null);return text;
    }
    private static JScrollPane code(String value,int width){
        JTextArea text=plain(value);text.setFont(new Font(Font.MONOSPACED,Font.PLAIN,11));text.getAccessibleContext().setAccessibleName("저장된 사용자 맞춤 지침 디버그 데이터");
        SmoothScrollPane scroll=new SmoothScrollPane(text);scroll.setBorder(null);scroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);scroll.getHorizontalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);scroll.getViewport().setBackground(AssistantChatTheme.BACKGROUND);scroll.setPreferredSize(new Dimension(width-28,280));return scroll;
    }
    static String describe(JsonObject snapshot){
        JsonObject values=snapshot.getAsJsonObject("values");StringBuilder text=new StringBuilder();
        for(String key:new String[]{"preferredName","language","tone","communicationStyle","responseLength"}){
            if(!values.has(key))continue;String value=values.get(key).getAsString();
            String label=switch(key){case "preferredName"->"호칭";case "language"->"답변 언어";case "tone"->"말투";case "communicationStyle"->"구체적인 대화 스타일";default->"답변 길이";};
            value=switch(key){
                case "tone"->switch(value){case "polite"->"존댓말";case "casual"->"반말";case "formal"->"격식체";default->value;};
                case "responseLength"->switch(value){case "concise"->"간결하게";case "balanced"->"적당한 길이로";case "detailed"->"자세하게";default->value;};
                case "language"->Locale.forLanguageTag(value).getDisplayName(Locale.KOREAN);
                default->value;
            };
            text.append(label).append(": ").append(value).append("\n\n");
        }
        if(values.has("notes")&&!values.getAsJsonArray("notes").isEmpty()){
            text.append("추가 지침\n");for(JsonElement note:values.getAsJsonArray("notes"))text.append("• ").append(note.getAsString()).append("\n");
        }
        return text.isEmpty()?"아직 저장된 사용자 맞춤 지침이 없어요.":text.toString().stripTrailing();
    }
}
