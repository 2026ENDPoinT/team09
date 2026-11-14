package dev.synesis.poc.ui;

import dev.synesis.poc.planner.PlannerModel.EventColor;
import java.awt.*;
import java.awt.event.*;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;
import javax.swing.*;
import static dev.synesis.poc.ui.PlannerStyle.*;

/** One horizontal palette; swatches are vectors so new colors need no image assets. */
final class PlannerColorPicker extends UnifiedScrollPane {
    final List<JButton> buttons=new ArrayList<>();
    private final JPanel row=new JPanel();
    private EventColor selected;
    private boolean positioned;

    PlannerColorPicker(EventColor selected,Consumer<EventColor> changed){
        super(VERTICAL_SCROLLBAR_NEVER,HORIZONTAL_SCROLLBAR_AS_NEEDED);
        this.selected=selected;row.setOpaque(false);row.setLayout(new BoxLayout(row,BoxLayout.X_AXIS));
        setViewportView(row);setBorder(null);setOpaque(false);getViewport().setBackground(Color.WHITE);
        name(this,"일정 색상 목록 · 가로 스크롤");
        getHorizontalScrollBar().setUI(new FadingScrollBarUI(NAVY,.3f));
        getHorizontalScrollBar().setPreferredSize(new Dimension(0,8));
        for(EventColor value:EventColor.values()){
            if(!buttons.isEmpty())row.add(Box.createHorizontalStrut(10));
            JButton button=new JButton(){@Override protected void paintComponent(Graphics graphics){
                Graphics2D g=quality(graphics);Color color=new Color(value.rgb),fill=PlannerEventCard.background(color);
                g.setColor(fill);g.fillOval(5,5,22,22);
                g.setColor(PlannerEventCard.accent(color));g.setStroke(new BasicStroke(1.5f));g.drawOval(5,5,21,21);
                if(value==PlannerColorPicker.this.selected || hasFocus()){
                    g.setColor(NAVY);g.setStroke(new BasicStroke(value==PlannerColorPicker.this.selected?2:1));g.drawOval(1,1,29,29);
                }
                if(value==PlannerColorPicker.this.selected){
                    g.setColor(PlannerEventCard.foreground(fill));g.setStroke(new BasicStroke(2,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                    g.drawLine(11,16,15,20);g.drawLine(15,20,21,12);
                }
                g.dispose();
            }};
            button.setBorder(null);button.setContentAreaFilled(false);button.setFocusPainted(false);
            Dimension size=new Dimension(32,32);button.setPreferredSize(size);button.setMinimumSize(size);button.setMaximumSize(size);
            name(button,value.label);button.setToolTipText(value.label);button.setSelected(value==selected);
            button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
            button.addActionListener(e->{this.selected=value;for(JButton swatch:buttons)swatch.setSelected(swatch==button);row.repaint();changed.accept(value);});
            button.addFocusListener(new FocusAdapter(){@Override public void focusGained(FocusEvent event){reveal(button);}});
            buttons.add(button);row.add(button);
        }
    }
    private void reveal(JButton button){
        Rectangle visible=getViewport().getViewRect(),bounds=button.getBounds();
        int x=visible.x;
        if(bounds.x<visible.x)x=bounds.x;
        else if(bounds.x+bounds.width>visible.x+visible.width)x=bounds.x+bounds.width-visible.width;
        getViewport().setViewPosition(new Point(Math.max(0,Math.min(x,row.getWidth()-visible.width)),0));
    }
    @Override public void doLayout(){
        super.doLayout();getViewport().doLayout();row.doLayout();
        if(!positioned && getViewport().getExtentSize().width>0 && row.getWidth()>0){
            positioned=true;reveal(buttons.get(selected.ordinal()));
        }
    }
}
