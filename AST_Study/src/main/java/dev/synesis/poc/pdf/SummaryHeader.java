package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;

/** A single header row; controls collapse before their full labels can overlap. */
final class SummaryHeader extends JPanel {
    private final JComponent title;
    private final JButton textSize,close;
    private final int fullTextWidth;
    private final String fullText;
    private final javax.swing.border.Border fullTextBorder;
    private boolean compact;

    SummaryHeader(JButton textSize,JButton close,JComponent title) {
        super(null);this.title=title;this.textSize=textSize;this.close=close;
        setBackground(MistWorkspaceTheme.HEADER);
        setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(0,0,1,0,MistWorkspaceTheme.LINE),new EmptyBorder(0,24,0,16)));
        setPreferredSize(new Dimension(1,42));setMinimumSize(new Dimension(0,42));
        fullTextWidth=textSize.getPreferredSize().width;fullText=textSize.getText();fullTextBorder=textSize.getBorder();
        textSize.setToolTipText("강의 해설 글자 크기 조절");textSize.getAccessibleContext().setAccessibleName("강의 해설 글자 크기 조절");
        add(title);add(textSize);add(close);
    }

    @Override public void doLayout() {
        Insets insets=getInsets();int left=insets.left,right=getWidth()-insets.right;
        int height=Math.max(0,getHeight()-insets.top-insets.bottom),top=insets.top;
        Dimension heading=title.getPreferredSize();
        int fullWidth=heading.width+12+fullTextWidth+8+32;
        boolean next=right-left<fullWidth;
        if(next!=compact){
            compact=next;
            textSize.setText(compact?"Aa":fullText);
            textSize.setBorder(compact?new EmptyBorder(0,0,0,0):fullTextBorder);
        }
        int textSizeWidth=compact?32:fullTextWidth;
        int toolsLeft=Math.max(left,right-textSizeWidth-8-32);
        title.setBounds(left,top+(height-heading.height)/2,Math.min(heading.width,Math.max(0,toolsLeft-left-12)),heading.height);
        textSize.setBounds(toolsLeft,top+(height-32)/2,textSizeWidth,32);
        close.setBounds(toolsLeft+textSizeWidth+8,top+(height-32)/2,32,32);
    }
}
