package dev.synesis.poc.ui;

import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.font.FontRenderContext;
import java.awt.font.TextLayout;
import java.util.LinkedHashMap;
import java.util.Map;

/** Bounded cache includes device scale and font rendering hints, never clip or color. */
final class PlannerTextLayout {
    private record Key(String text,Font font,FontRenderContext context){}
    private static final Map<Key,TextLayout> CACHE=new LinkedHashMap<>(128,.75f,true){
        @Override protected boolean removeEldestEntry(Map.Entry<Key,TextLayout> entry){return size()>512;}
    };
    static synchronized TextLayout get(Graphics2D g,String text,Font font){
        Key key=new Key(text,font,g.getFontRenderContext());
        return CACHE.computeIfAbsent(key,k->new TextLayout(k.text(),k.font(),k.context()));
    }
    private PlannerTextLayout(){}
}
