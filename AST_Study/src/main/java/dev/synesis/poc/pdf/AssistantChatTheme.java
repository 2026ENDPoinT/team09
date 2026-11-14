package dev.synesis.poc.pdf;

import java.awt.Color;
import javax.swing.JComponent;

/** Instance-only palette for the home assistant, independent of the study workspace. */
final class AssistantChatTheme {
    static final Color BACKGROUND=new Color(0x20242b), SURFACE=new Color(0x292e38),
        USER=new Color(0x343d4f), TEXT=new Color(0xf3f5f9), MUTED=new Color(0xa6b2c5),
        LINE=new Color(0x414a5a), CODE=new Color(0xfafafa);
    // Home-assistant inline code only: 90% answer surface + 10% white.
    static final Color INLINE_CODE=new Color(0x3e434c);
    static Color codeForeground(Color color){
        if(color==null)return new Color(0x24272c);
        return switch(color.getRGB()&0xffffff){
            case 0xf3f5f9 -> new Color(0x24272c);
            case 0xa6b2c5 -> new Color(0x6d7780);
            case 0x8ed8b5 -> new Color(0x18735a);
            case 0xf0b87b -> new Color(0xb95419);
            case 0xf0a0c5 -> new Color(0xbf386e);
            case 0xc4b1f2 -> new Color(0x7040b5);
            default -> color;
        };
    }
    static void configure(JComponent component) {
        component.putClientProperty("synesis.assistantDark",true);
        component.setBackground(SURFACE);component.setForeground(TEXT);
    }
    static String document(String html) {
        // Only renderer-owned HTML is passed here; stored Markdown stays unchanged.
        return html.replace("#252629","#f3f5f9").replace("#141414","#f3f5f9")
            .replace("#182234","#f3f5f9").replace("#45474c","#a6b2c5")
            .replace("#61656c","#a6b2c5").replace("#24272c","#f3f5f9")
            .replace("#dfe9f7","#414a5a").replace("#f8f8f8","#fafafa")
            .replace("#f2f7ff","#fafafa")
            .replace(dev.synesis.poc.ui.MistWorkspaceTheme.SOFT_HEX,"#323a48")
            .replace("#6d7780","#a6b2c5").replace("#fff3dc","#493e2a")
            .replace("#18735a","#8ed8b5").replace("#b95419","#f0b87b")
            .replace("#bf386e","#f0a0c5").replace("#7040b5","#c4b1f2");
    }
}
