package dev.synesis.poc.pdf;

import java.awt.*;
import java.util.Set;
import java.util.regex.*;
import javax.swing.text.*;
import javax.swing.text.html.*;

/** Static Swing text styling: no web renderer, raster caches or animation. */
final class StudyCodeBlock {
    static final String BACKGROUND = "#f8f8f8";
    static final String INLINE_BACKGROUND = "#f2f7ff";
    private static final Pattern BLOCK=Pattern.compile("(?s)<pre\\b[^>]*>(.*?)</pre>");
    private static final Pattern TOKEN=Pattern.compile("(?m)//[^\\n]*|/\\*[\\s\\S]*?\\*/|&quot;.*?&quot;|\"[^\"\\n]*\"|'[^'\\n]*'|&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z]+);|\\b[0-9]+(?:\\.[0-9]+)?\\b|\\b[A-Za-z_][A-Za-z_0-9]*\\b");
    private static final Set<String> KEYWORDS=Set.of("typedef","enum","class","struct","namespace","using","const","static","public","private","protected","return","if","else","for","while","switch","case","break","continue","new","delete","template","typename","include","import","from","def","function","let","var","async","await","try","catch","throw");
    private static final Set<String> TYPES=Set.of("int","long","float","double","char","bool","void","auto","string","std","cout","cin","endl","True","False","true","false","None","null");
    static String decorate(String html) {
        if(html==null || !html.contains("<pre"))return html;
        Matcher blocks=BLOCK.matcher(html);StringBuffer result=new StringBuffer();
        while(blocks.find()) {
            String code=normalize(blocks.group(1).replaceAll("</?code\\b[^>]*>",""));
            Matcher tokens=TOKEN.matcher(code);StringBuffer painted=new StringBuffer();
            while(tokens.find()) {
                String token=tokens.group(),color=token.startsWith("//")||token.startsWith("/*")?"#6d7780":
                    token.startsWith("\"")||token.startsWith("'")||token.startsWith("&quot;")?"#18735a":
                    Character.isDigit(token.charAt(0))?"#b95419":KEYWORDS.contains(token)?"#bf386e":TYPES.contains(token)?"#7040b5":null;
                tokens.appendReplacement(painted,Matcher.quoteReplacement(color==null?token:"<font color='"+color+"'>"+token+"</font>"));
            }
            tokens.appendTail(painted);
            blocks.appendReplacement(result,Matcher.quoteReplacement("<pre style='background:"+BACKGROUND+";color:#24272c;padding:0;margin:0;'>"+painted+"</pre>"));
        }
        blocks.appendTail(result);return result.toString();
    }
    /** Trim presentation-only outer blank lines; retain all indentation and internal lines. */
    static String normalize(String code) {
        return code.replaceAll("\\A(?:[ \\t]*\\r?\\n)+", "")
            .replaceAll("(?:\\r?\\n[ \\t]*)+\\z", "")+"\n";
    }

    static boolean insideCode(Element element) {
        for(Element parent=element.getParentElement();parent!=null;parent=parent.getParentElement())
            if(parent.getAttributes().getAttribute(StyleConstants.NameAttribute)==HTML.Tag.PRE)return true;
        return false;
    }

    static View line(Element element) {
        return new javax.swing.text.html.ParagraphView(element) {
            private int tabWidth;
            @Override public float nextTabStop(float x,int tabOffset) {
                // Swing's prose default is 72 pixels. Code uses four fixed-width spaces,
                // measured once per line, without replacing the original tab characters.
                if(tabWidth<=0) {
                    Font font=getLayoutViewCount()>0 && getLayoutView(0) instanceof GlyphView glyph
                        ?glyph.getFont():getContainer().getFont();
                    font=new Font(Font.MONOSPACED,font.getStyle(),font.getSize());
                    tabWidth=Math.max(1,getContainer().getFontMetrics(font).stringWidth("    "));
                }
                float base=getTabBase();
                return base+((float)Math.floor((x-base)/tabWidth)+1)*tabWidth;
            }
            @Override protected void setPropertiesFromAttributes() {
                super.setPropertiesFromAttributes();
                setInsets((short)0,(short)0,(short)0,(short)0);
                setLineSpacing(.12f);setFirstLineIndent(0);setJustification(StyleConstants.ALIGN_LEFT);tabWidth=0;
            }
            @Override public float getMinimumSpan(int axis) {return axis==View.X_AXIS?0:super.getMinimumSpan(axis);}
            @Override public boolean isVisible(){return true;}
        };
    }

    static View token(Element element) {
        return new InlineView(element) {
            private AttributeSet wrapping;
            private Font codeFont;
            @Override public Color getForeground(){
                Color color=super.getForeground();
                return getContainer() instanceof javax.swing.JComponent c&&Boolean.TRUE.equals(c.getClientProperty("synesis.assistantDark"))
                    ?AssistantChatTheme.codeForeground(color):color;
            }
            @Override public Font getFont() {
                if(codeFont==null) {Font base=super.getFont();codeFont=new Font(Font.MONOSPACED,base.getStyle(),base.getSize());}
                return codeFont;
            }
            @Override public AttributeSet getAttributes() {
                if(wrapping==null) {
                    SimpleAttributeSet attributes=new SimpleAttributeSet(super.getAttributes());
                    new StyleSheet().addCSSAttribute(attributes,CSS.Attribute.WHITE_SPACE,"normal");
                    wrapping=attributes;
                }
                return wrapping;
            }
            @Override public float getMinimumSpan(int axis) {return axis==View.X_AXIS?0:super.getMinimumSpan(axis);}
        };
    }

    static View view(Element element) {
        return new BlockView(element,View.Y_AXIS) {
            @Override protected void setPropertiesFromAttributes() {
                super.setPropertiesFromAttributes();setInsets((short)12,(short)14,(short)12,(short)14);
            }
            @Override public float getMinimumSpan(int axis) {return axis==View.X_AXIS?32:super.getMinimumSpan(axis);}
            @Override public void paint(Graphics graphics,Shape allocation) {
                Graphics2D g=(Graphics2D)graphics.create();Rectangle r=allocation.getBounds();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    Shape shape=new java.awt.geom.RoundRectangle2D.Float(r.x+.5f,r.y+.5f,Math.max(0,r.width-1),Math.max(0,r.height-1),16,16);
                    boolean assistantDark=getContainer() instanceof javax.swing.JComponent c
                        && Boolean.TRUE.equals(c.getClientProperty("synesis.assistantDark"));
                    g.setColor(assistantDark?AssistantChatTheme.CODE:Color.decode(BACKGROUND));g.fill(shape);
                    Shape previous=g.getClip();g.clip(shape);super.paint(g,allocation);g.setClip(previous);
                    g.setStroke(new BasicStroke(1));g.setColor(Color.BLACK);g.draw(shape);
                } finally {g.dispose();}
            }
        };
    }
}
