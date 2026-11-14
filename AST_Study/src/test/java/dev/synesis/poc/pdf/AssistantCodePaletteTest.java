package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import javax.swing.*;
import javax.swing.text.*;

/** Offscreen: dark assistant prose with light code paper and readable syntax. */
public final class AssistantCodePaletteTest {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static GlyphView glyph(View view,int at){
        if(view instanceof GlyphView g&&at>=g.getStartOffset()&&at<g.getEndOffset())return g;
        for(int i=0;i<view.getViewCount();i++){GlyphView g=glyph(view.getView(i),at);if(g!=null)return g;}return null;
    }
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{try{
            StudyHtmlPane pane=new StudyHtmlPane(true);pane.setReadingSkin(true);AssistantChatTheme.configure(pane);
            String code="long long fibonacci(int n) {\n    if (n < 2) return n;\n    return fibonacci(n - 1) + fibonacci(n - 2);\n}\n";
            String markdown="코드 `fibonacci`예요.\n\n```cpp\n"+code+"```\n\n\\[x^2=9\\]";
            pane.setText(AssistantChatTheme.document(SummarySkin.formulaDocument(StudyMarkdown.render(markdown,14),14)));
            pane.setSize(420,2000);pane.modelToView2D(0);View root=pane.getUI().getRootView(pane);root.setSize(420,2000);
            pane.setSize(420,(int)Math.ceil(root.getPreferredSpan(View.Y_AXIS)));
            String text=pane.getDocument().getText(0,pane.getDocument().getLength());check(text.contains(code),"copied code changed");
            Color inline=glyph(root,text.indexOf("fibonacci")).getForeground();
            Color ordinary=glyph(root,text.indexOf("fibonacci(int")).getForeground();
            Color keyword=glyph(root,text.indexOf("return")).getForeground();
            check(inline.equals(AssistantChatTheme.TEXT),"inline code text lacks light contrast");
            check(ordinary.getRed()<70&&ordinary.getGreen()<70&&ordinary.getBlue()<70,"code body text lacks dark contrast: "+ordinary);
            check(keyword.equals(new Color(0xbf386e)),"keyword does not use light-paper palette");
            BufferedImage image=new BufferedImage(pane.getWidth(),pane.getHeight(),BufferedImage.TYPE_INT_RGB);
            Graphics2D g=image.createGraphics();g.setColor(AssistantChatTheme.SURFACE);g.fillRect(0,0,image.getWidth(),image.getHeight());pane.paint(g);g.dispose();
            int light=0;for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++)if((image.getRGB(x,y)&0xffffff)==0xfafafa)light++;
            check(light>3000,"code paper is not white toned");image.flush();
            System.out.println("AssistantCodePaletteTest OK · white code paper, dark inline/body text, syntax contrast, copied code retained");
        }catch(Exception e){throw new RuntimeException(e);}});
    }
}
