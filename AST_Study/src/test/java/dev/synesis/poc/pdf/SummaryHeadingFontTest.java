package dev.synesis.poc.pdf;

import java.util.*;
import javax.swing.*;
import javax.swing.text.*;

/** Exercise resolved Swing glyph fonts: grouped CSS selectors silently fall back to tiny defaults. */
public final class SummaryHeadingFontTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            check(18,new int[]{26,23,22,20,20,20});
            check(36,new int[]{52,45,44,40,40,40});
        });
        System.out.println("Summary heading fonts use the requested hierarchy and scale with body text");
    }
    private static void check(int body,int[] expected) {
        String[] labels={"LEVELONE","LEVELTWO","LEVELTHREE","채무시장","지분시장","자본시장"};
        StringBuilder html=new StringBuilder();
        for(int i=0;i<labels.length;i++)html.append("<h").append(i+1).append('>').append(labels[i])
            .append("</h").append(i+1).append('>');
        html.append("<p>BODY</p>");
        StudyHtmlPane pane=new StudyHtmlPane(true);pane.setReadingSkin(true);
        pane.setText(SummarySkin.document("",html.toString(),body));pane.setSize(1400,3000);pane.getPreferredSize();
        Map<String,Integer> fonts=new LinkedHashMap<>();collect(pane.getUI().getRootView(pane),fonts);
        for(int i=0;i<labels.length;i++)if(!Objects.equals(fonts.get(labels[i]),expected[i]))
            throw new AssertionError(labels[i]+" at body "+body+": expected "+expected[i]+", got "+fonts.get(labels[i]));
        if(!Objects.equals(fonts.get("BODY"),body))throw new AssertionError("Body size changed");
    }
    private static void collect(View view,Map<String,Integer> fonts) {
        if(view instanceof GlyphView glyph)try {
            String text=glyph.getDocument().getText(glyph.getStartOffset(),glyph.getEndOffset()-glyph.getStartOffset()).strip();
            if(!text.isEmpty())fonts.put(text,glyph.getFont().getSize());
        } catch(BadLocationException failure) {throw new AssertionError(failure);}
        for(int i=0;i<view.getViewCount();i++)collect(view.getView(i),fonts);
    }
}
