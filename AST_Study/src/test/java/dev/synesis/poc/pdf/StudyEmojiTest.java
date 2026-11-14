package dev.synesis.poc.pdf;

import java.awt.*;
import javax.swing.*;
import javax.swing.text.*;

/** Offline checks of the actual mentor font resolver, including copyable emoji sequences. */
public final class StudyEmojiTest {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static GlyphView glyph(View view,int position){
        if(view instanceof GlyphView g&&position>=g.getStartOffset()&&position<g.getEndOffset())return g;
        for(int i=0;i<view.getViewCount();i++){GlyphView g=glyph(view.getView(i),position);if(g!=null)return g;}return null;
    }
    static StudyHtmlPane pane(Container c){for(Component child:c.getComponents()){if(child instanceof StudyHtmlPane p)return p;if(child instanceof Container nested){StudyHtmlPane p=pane(nested);if(p!=null)return p;}}return null;}
    public static void main(String[] args)throws Exception{
        System.setProperty("synesis.dataRoot",java.nio.file.Files.createTempDirectory("emoji-font-").toString());
        SwingUtilities.invokeAndWait(()->{try{
            String message="본문은 그대로 🙂 👍🏽 👩‍💻 🇰🇷 1️⃣ ❤️ 끝이에요.";
            JPanel bubble=PdfWorkspace.assistantAnswerBubble(StudyMarkdown.render(message,14),420,14,ignored->{});
            StudyHtmlPane html=pane(bubble);html.setSize(380,Short.MAX_VALUE);html.modelToView2D(0);
            String plain=html.getDocument().getText(0,html.getDocument().getLength());
            check(plain.contains(message),"emoji text/sequence changed during rendering or copying");
            View root=html.getUI().getRootView(html);
            Font prose=glyph(root,plain.indexOf("본문")).getFont();
            check(prose.getFontName().contains("Noto Sans KR"),"prose font changed");
            for(String emoji:new String[]{"🙂","👍🏽","👩‍💻","🇰🇷","1️⃣","❤️"}){
                Font face=glyph(root,plain.indexOf(emoji)).getFont();
                check(!face.getFamily().equals(prose.getFamily()),"emoji still uses prose font");
                check(face.canDisplay(emoji.codePointAt(0)),"emoji glyph unavailable: "+emoji);
            }
            System.out.println("StudyEmojiTest OK · prose preserved; smile, skin tone, ZWJ, flag, keycap and heart use emoji font; copy text intact");
        }catch(Exception e){throw new RuntimeException(e);}});
    }
}
