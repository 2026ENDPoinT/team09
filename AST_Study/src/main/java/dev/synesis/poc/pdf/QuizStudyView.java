package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryMotionClock;
import java.awt.*;
import java.awt.event.*;
import java.util.List;
import java.util.*;
import java.util.function.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;

/** A single live HTML/math card regardless of workbook size. Other questions retain only answer data. */
final class QuizStudyView extends JPanel {
    private static final QuizWorkbook.Answer EMPTY=new QuizWorkbook.Answer("",false);
    private final JPanel body=column(18),questionColumn=column(16),cardHost=new JPanel(new BorderLayout());
    private final JPanel workspace=new JPanel(new WorkspaceLayout());
    private final JPanel indexPanel=QuizPlayDesign.panel(new QuizQuestionCard.StackLayout(16),20);
    private final JPanel grid=new JPanel(new GridLayout(0,5,8,8));
    private final QuizScrollPane gridScroll=new QuizScrollPane(grid,JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
    private final JTextArea title=copy("",30),subtitle=copy("",13),created=copy("",11),notice=copy("",11);
    private final JLabel accuracy=QuizPlayDesign.label("정답률 0%",11,false);
    private final JLabel solved=QuizPlayDesign.label("0 / 0",18,true),correct=QuizPlayDesign.label("0",18,true),position=QuizPlayDesign.label("",12,false);
    final JButton all=QuizPlayDesign.button("전체 0",false),marked=QuizPlayDesign.button("체크 0",false);
    final JButton previous=QuizPlayDesign.button("이전 문제",false),next=QuizPlayDesign.button("다음 문제",true);
    final JButton indexButton=QuizPlayDesign.button("문제 인덱스",false);
    final JPanel navigation=new JPanel(new NavigationLayout());
    private final QuizPlayDesign.Progress progress=new QuizPlayDesign.Progress();
    private final Popup popup=new Popup();
    private final JPanel empty=QuizPlayDesign.panel(new BorderLayout(),30);
    private final List<IndexCell> cells=new ArrayList<>();
    private List<QuizQuestion> items=List.of();
    private final Map<String,QuizWorkbook.Answer> answers=new LinkedHashMap<>();
    private QuizQuestionCard active;
    private int current;
    private boolean onlyMarked;
    private BiFunction<QuizQuestion,Integer,QuizQuestionCard> factory;
    private Consumer<QuizQuestionCard> activeChanged=card->{};
    private Runnable changed=()->{},scrollTop=()->{};

    QuizStudyView(JButton back) {
        super(null);setLayout(new PageLayout());setOpaque(false);
        body.setBorder(new EmptyBorder(10,6,24,6));add(body);
        JPanel nav=new JPanel(new BorderLayout());nav.setOpaque(false);nav.add(back,BorderLayout.WEST);
        indexButton.setIcon(QuizPlayDesign.icon("grid",16));nav.add(indexButton,BorderLayout.EAST);body.add(nav);
        JPanel heading=new JPanel(new HeadingLayout());heading.setOpaque(false);
        heading.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(0,0,1,0,QuizPlayDesign.LINE),new EmptyBorder(4,0,24,0)));
        JPanel headingCopy=column(10);title.setFont(dev.synesis.poc.ui.MistWorkspaceTheme.font(Font.PLAIN,30));title.setForeground(QuizPlayDesign.INK);
        title.setName("quiz-workbook-title");subtitle.setName("quiz-workbook-metadata");created.setName("quiz-workbook-created");
        subtitle.setFont(dev.synesis.poc.ui.MistWorkspaceTheme.font(Font.BOLD,13));
        subtitle.setForeground(QuizPlayDesign.TEXT);headingCopy.add(subtitle);headingCopy.add(title);
        headingCopy.add(copy("PDF 개념을 문제로 확인하고, 해설과 함께 복습해 보세요.",13));
        headingCopy.add(created);created.setVisible(false);
        JPanel stats=QuizPlayDesign.panel(new QuizQuestionCard.StackLayout(12),16);
        JPanel statsTop=new JPanel(new BorderLayout(8,0));statsTop.setOpaque(false);
        JLabel progressLabel=QuizPlayDesign.label("학습 진행률",11,false);progressLabel.setForeground(QuizPlayDesign.MUTED);
        statsTop.add(progressLabel,BorderLayout.WEST);statsTop.add(solved,BorderLayout.EAST);stats.add(statsTop);stats.add(progress);
        JPanel statsMeta=new JPanel(new BorderLayout(8,0));statsMeta.setOpaque(false);
        correct.setFont(dev.synesis.poc.ui.MistWorkspaceTheme.font(Font.PLAIN,11));correct.setForeground(QuizPlayDesign.MUTED);accuracy.setForeground(QuizPlayDesign.MUTED);
        statsMeta.add(correct,BorderLayout.WEST);statsMeta.add(accuracy,BorderLayout.EAST);stats.add(statsMeta);
        heading.add(headingCopy);heading.add(stats);body.add(heading);
        notice.setVisible(false);body.add(notice);
        workspace.setOpaque(false);cardHost.setOpaque(false);questionColumn.add(cardHost);
        navigation.setOpaque(false);navigation.setBorder(new EmptyBorder(0,2,0,2));
        previous.setIcon(QuizPlayDesign.icon("left",16));next.setIcon(QuizPlayDesign.icon("right",16));next.setHorizontalTextPosition(SwingConstants.LEFT);
        position.setHorizontalAlignment(SwingConstants.CENTER);navigation.add(previous,BorderLayout.WEST);navigation.add(position);navigation.add(next,BorderLayout.EAST);
        workspace.add(questionColumn);workspace.add(indexPanel);body.add(workspace);
        empty.add(copy("체크한 문제가 없어요. 다시 볼 문제를 체크해 두세요.",12));
        JLabel indexTitle=QuizPlayDesign.label("문제 인덱스",15,true);indexTitle.setIcon(QuizPlayDesign.icon("grid",18));indexTitle.setIconTextGap(9);indexPanel.add(indexTitle);
        JPanel tabs=new JPanel(new GridLayout(1,2,3,0));tabs.setOpaque(true);tabs.setBackground(QuizPlayDesign.SOFT);tabs.setBorder(new EmptyBorder(3,3,3,3));tabs.add(all);tabs.add(marked);
        marked.setIcon(QuizPlayDesign.icon("bookmark",14));indexPanel.add(tabs);
        all.putClientProperty("quiz.tab",true);marked.putClientProperty("quiz.tab",true);
        grid.setOpaque(false);grid.setBorder(new EmptyBorder(4,4,4,4));gridScroll.setBorder(null);gridScroll.getViewport().setBackground(Color.WHITE);gridScroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        indexPanel.add(gridScroll);
        JLabel legend=QuizPlayDesign.label("■ 정답   ▧ 오답   ▣ 선택   □ 미풀이",10,false);legend.setForeground(QuizPlayDesign.MUTED);indexPanel.add(legend);
        JPanel tip=new JPanel(new BorderLayout(8,0));tip.setOpaque(true);tip.setBackground(QuizPlayDesign.SOFT);tip.setBorder(new EmptyBorder(11,11,11,11));
        tip.add(new JLabel(QuizPlayDesign.icon("lightbulb",17)),BorderLayout.WEST);tip.add(copy("헷갈리는 문제는 문제 체크 후 모아서 복습할 수 있어요.",10));indexPanel.add(tip);
        all.addActionListener(e->filter(false));marked.addActionListener(e->filter(true));
        previous.addActionListener(e->move(-1));next.addActionListener(e->move(1));indexButton.addActionListener(e->openIndex());
        popup.addPopupMenuListener(new javax.swing.event.PopupMenuListener(){
            public void popupMenuWillBecomeVisible(javax.swing.event.PopupMenuEvent e){}
            public void popupMenuCanceled(javax.swing.event.PopupMenuEvent e){SwingUtilities.invokeLater(workspace::revalidate);}
            public void popupMenuWillBecomeInvisible(javax.swing.event.PopupMenuEvent e){SwingUtilities.invokeLater(workspace::revalidate);}
        });
    }
    private static JPanel column(int gap){JPanel panel=new JPanel(new QuizQuestionCard.StackLayout(gap));panel.setOpaque(false);return panel;}
    private static JTextArea copy(String text,int font){
        JTextArea area=new JTextArea(text);area.setEditable(false);area.setFocusable(false);area.setLineWrap(true);area.setWrapStyleWord(true);area.setOpaque(false);
        area.setFont(dev.synesis.poc.ui.MistWorkspaceTheme.font(Font.PLAIN,font));area.setForeground(QuizPlayDesign.MUTED);area.setBorder(null);area.putClientProperty("synesis.preserveFont",true);return area;
    }
    void configure(BiFunction<QuizQuestion,Integer,QuizQuestionCard> factory,Consumer<QuizQuestionCard> activeChanged,Runnable changed,Runnable scrollTop){
        this.factory=factory;this.activeChanged=activeChanged;this.changed=changed;this.scrollTop=scrollTop;
    }
    void heading(String name,String meta,String note){
        title.setText(name);String[] lines=meta.split("\\R",2);subtitle.setText(lines[0]);
        created.setText(lines.length>1?lines[1]:"");created.setVisible(!created.getText().isBlank());
        notice.setText(note);notice.setVisible(!note.isBlank());
    }
    void open(List<QuizQuestion> questions,Map<String,QuizWorkbook.Answer> saved,boolean preview){
        clear();items=List.copyOf(questions);answers.putAll(saved);current=0;onlyMarked=false;rebuildIndex();showCurrent();
    }
    void update(List<QuizQuestion> questions){
        String currentId=active==null?"":active.question.id();items=List.copyOf(questions);
        answers.keySet().retainAll(items.stream().map(QuizQuestion::id).toList());
        for(int i=0;i<items.size();i++)if(items.get(i).id().equals(currentId)){current=i;break;}
        rebuildIndex();
        if(active==null||!items.contains(active.question))showCurrent();else {active.setQuestionNumber(current+1);refreshSummary();}
    }
    void clear(){
        popup.setVisible(false);active=null;activeChanged.accept(null);items=List.of();answers.clear();cells.clear();grid.removeAll();cardHost.removeAll();
    }
    int questionCount(){return items.size();}
    /** Full workbook width, including the index; independent of document scroll position. */
    Rectangle navigationColumn(int width){
        int page=Math.min(1180,width),available=Math.max(1,page-body.getInsets().left-body.getInsets().right);
        return new Rectangle((width-page)/2+body.getInsets().left,0,available,0);
    }
    int currentIndex(){return current;}
    QuizQuestionCard currentCard(){return active;}
    Map<String,QuizWorkbook.Answer> snapshot(){return Map.copyOf(answers);}
    void select(int index){
        if(index<0||index>=items.size()||onlyMarked&&!answer(index).bookmarked())return;
        popup.setVisible(false);
        if(current==index&&active!=null)return;
        current=index;showCurrent();scrollTop.run();
    }
    private QuizWorkbook.Answer answer(int index){return answers.getOrDefault(items.get(index).id(),EMPTY);}
    private List<Integer> visible(){
        List<Integer> result=new ArrayList<>();for(int i=0;i<items.size();i++)if(!onlyMarked||answer(i).bookmarked())result.add(i);return result;
    }
    private void move(int step){List<Integer> visible=visible();int pos=visible.indexOf(current),next=pos+step;if(pos>=0&&next>=0&&next<visible.size())select(visible.get(next));}
    private void filter(boolean value){
        onlyMarked=value;List<Integer> visible=visible();
        if(active==null||!visible.contains(current)){current=visible.isEmpty()?0:visible.getFirst();showCurrent();}
        rebuildIndex();refreshSummary();scrollTop.run();
    }
    void refreshQuestion(){
        if(active==null)return;
        answers.put(active.question.id(),active.snapshot());
        showCurrent();
    }
    private void showCurrent(){
        active=null;activeChanged.accept(null);cardHost.removeAll();
        if(items.isEmpty()||onlyMarked&&!answer(current).bookmarked())cardHost.add(empty);
        else {
            QuizQuestion question=items.get(current);QuizQuestionCard card=factory.apply(question,current+1);
            card.restore(answers.get(question.id()));active=card;activeChanged.accept(card);
            card.setAnswerChangeHandler(value->{
                if(active!=card)return;
                QuizWorkbook.Answer before=answers.put(question.id(),value);
                refreshSummary();cells.get(current).repaint();changed.run();
                if(onlyMarked&&before!=null&&before.bookmarked()!=value.bookmarked()){
                    List<Integer> visible=visible();current=visible.isEmpty()?0:visible.getFirst();rebuildIndex();showCurrent();
                }
            });
            cardHost.add(card);
        }
        refreshSummary();revalidate();repaint();
    }
    private void rebuildIndex(){
        grid.removeAll();
        while(cells.size()>items.size())cells.removeLast();
        for(int i=0;i<items.size();i++){IndexCell cell=i<cells.size()?cells.get(i):new IndexCell(i);if(i==cells.size())cells.add(cell);cell.refresh();if(!onlyMarked||answer(i).bookmarked())grid.add(cell);}
        if(grid.getComponentCount()==0)grid.add(QuizPlayDesign.label("없음",11,false));
        int rows=Math.max(1,(grid.getComponentCount()+4)/5);gridScroll.setPreferredSize(new Dimension(252,Math.min(344,rows*46+8)));
        gridScroll.getViewport().setViewPosition(new Point());indexPanel.revalidate();indexPanel.repaint();
    }
    private void refreshSummary(){
        int done=0,right=0,markedCount=0;
        for(int i=0;i<items.size();i++){
            var a=answer(i);if(a.revealed())done++;if(status(i).equals("정답"))right++;if(a.bookmarked())markedCount++;
        }
        solved.setText(done+" / "+items.size());correct.setText("정답 "+right);accuracy.setText("정답률 "+(done==0?0:Math.round(100d*right/done))+"%");progress.setProgress(done,items.size());
        all.setText("전체 "+items.size());marked.setText("체크 "+markedCount);all.setSelected(!onlyMarked);marked.setSelected(onlyMarked);
        all.setForeground(!onlyMarked?QuizPlayDesign.INK:QuizPlayDesign.MUTED);marked.setForeground(onlyMarked?QuizPlayDesign.INK:QuizPlayDesign.MUTED);
        List<Integer> visible=visible();int pos=visible.indexOf(current);previous.setEnabled(pos>0);next.setEnabled(pos>=0&&pos+1<visible.size());
        position.setText(active==null?"":(current+1)+" / "+items.size()+(onlyMarked?" · 체크 "+(pos+1)+" / "+visible.size():""));
        for(IndexCell cell:cells)cell.refresh();
    }
    private String status(int index){
        var value=answer(index);QuizQuestion question=items.get(index);
        if(!value.revealed())return value.answer().isBlank()?"미풀이":"답안 선택됨";
        if(value.skipped())return "오답";
        if(question.selfComparison())return "확인 완료";
        return question.answer().equals(value.answer())?"정답":"오답";
    }
    private void openIndex(){
        if(items.isEmpty())return;
        if(workspace.getWidth()>=860&&indexPanel.getParent()==workspace){indexPanel.scrollRectToVisible(indexPanel.getVisibleRect());return;}
        indexPanel.setVisible(true);
        if(indexPanel.getParent()!=popup){if(indexPanel.getParent()!=null)indexPanel.getParent().remove(indexPanel);popup.add(indexPanel);}
        int width=Math.min(300,Math.max(230,getWidth()-16));popup.setPopupSize(width,Math.min(550,indexPanel.getPreferredSize().height+4));
        popup.show(indexButton,Math.min(0,indexButton.getWidth()-width),indexButton.getHeight()+6);popup.begin();
    }
    @Override public void removeNotify(){popup.setVisible(false);super.removeNotify();}
    private final class IndexCell extends QuizPlayDesign.Button {
        final int index;String state="";boolean bookmark,isCurrent;
        IndexCell(int index){super(String.valueOf(index+1),false);this.index=index;setBorder(new EmptyBorder(0,0,0,0));setPreferredSize(new Dimension(40,38));addActionListener(e->select(index));refresh();}
        void refresh(){String next=status(index);boolean mark=answer(index).bookmarked(),selected=active!=null&&current==index;
            if(!next.equals(state)||mark!=bookmark||selected!=isCurrent){state=next;bookmark=mark;isCurrent=selected;setForeground(state.equals("정답")?Color.WHITE:QuizPlayDesign.TEXT);repaint();}
            String name=(index+1)+"번 문제, "+state+(bookmark?", 체크됨":"");if(!name.equals(getAccessibleContext().getAccessibleName()))getAccessibleContext().setAccessibleName(name);
        }
        @Override protected Color fill(){return state.equals("정답")?QuizPlayDesign.INK:state.equals("미풀이")?super.fill():QuizPlayDesign.SOFT;}
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Graphics2D g=(Graphics2D)graphics.create();try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                if(state.equals("오답")){g.setColor(QuizPlayDesign.MUTED);g.setStroke(new BasicStroke(1,0,0,10,new float[]{3,3},0));g.drawRoundRect(2,2,getWidth()-5,getHeight()-5,14,14);}
                if(isCurrent){g.setColor(QuizPlayDesign.INK);g.setStroke(new BasicStroke(1.8f));g.drawRoundRect(0,0,getWidth()-1,getHeight()-1,18,18);}
                if(bookmark){g.setColor(state.equals("정답")?Color.WHITE:QuizPlayDesign.INK);g.fillOval(getWidth()-9,5,4,4);}
            }finally{g.dispose();}
        }
    }
    private final class Popup extends JPopupMenu implements LibraryMotionClock.Task {
        private long started;private double amount=1;
        void begin(){started=System.nanoTime();amount=0;if(LibraryMotionClock.reduced()||!LibraryMotionClock.add(this)){amount=1;repaint();}}
        public boolean advance(long now){if(!isShowing()){amount=1;return false;}double t=Math.min(1,(now-started)/220_000_000d);amount=LibraryMotionClock.ease(t);repaint();return t<1;}
        @Override public void paint(Graphics graphics){Graphics2D g=(Graphics2D)graphics.create();try{g.translate((1-amount)*18,0);super.paint(g);}finally{g.dispose();}}
        @Override public void removeNotify(){LibraryMotionClock.remove(this);amount=1;super.removeNotify();}
    }
    private static final class NavigationLayout extends BorderLayout {
        NavigationLayout(){super(8,0);}
        @Override public void layoutContainer(Container parent){
            Insets inset=parent.getInsets();
            int width=parent.getWidth()-inset.left-inset.right;
            if(width<640){super.layoutContainer(parent);return;}
            Component previous=getLayoutComponent(WEST),position=getLayoutComponent(CENTER),next=getLayoutComponent(EAST);
            int middle=Math.max(80,position.getPreferredSize().width+24),gap=getHgap();
            int buttonWidth=Math.max(1,(width-middle-gap*2)/2),height=parent.getHeight()-inset.top-inset.bottom;
            previous.setBounds(inset.left,inset.top,buttonWidth,height);
            position.setBounds(inset.left+buttonWidth+gap,inset.top,middle,height);
            int right=inset.left+buttonWidth+gap+middle+gap;
            next.setBounds(right,inset.top,Math.max(1,inset.left+width-right),height);
        }
    }
    private final class PageLayout implements LayoutManager {
        public void addLayoutComponent(String n,Component c){}public void removeLayoutComponent(Component c){}
        public Dimension minimumLayoutSize(Container p){return new Dimension(0,0);}
        public Dimension preferredLayoutSize(Container p){int width=p.getWidth()>0?p.getWidth():650;body.setSize(Math.min(1180,width),Math.max(1,body.getHeight()));return new Dimension(width,body.getPreferredSize().height);}
        public void layoutContainer(Container p){int width=Math.min(1180,p.getWidth());body.setBounds((p.getWidth()-width)/2,0,width,p.getHeight());body.doLayout();}
    }
    private final class WorkspaceLayout implements LayoutManager {
        public void addLayoutComponent(String n,Component c){}public void removeLayoutComponent(Component c){}
        public Dimension minimumLayoutSize(Container p){return new Dimension(0,0);}
        private boolean wide(Container p){return p.getWidth()>=860&&!popup.isVisible();}
        public Dimension preferredLayoutSize(Container p){int width=p.getWidth()>0?p.getWidth():650;boolean wide=wide(p);questionColumn.setSize(Math.max(1,width-(wide?314:0)),Math.max(1,questionColumn.getHeight()));indexPanel.setSize(292,Math.max(1,indexPanel.getHeight()));return new Dimension(width,Math.max(questionColumn.getPreferredSize().height,wide?indexPanel.getPreferredSize().height:0));}
        public void layoutContainer(Container p){
            boolean wide=wide(p);int width=p.getWidth();
            if(indexButton.isVisible()==wide)indexButton.setVisible(!wide);
            if(wide&&indexPanel.getParent()!=workspace){if(indexPanel.getParent()!=null)indexPanel.getParent().remove(indexPanel);workspace.add(indexPanel);}
            if(indexPanel.getParent()==workspace)indexPanel.setVisible(wide);
            questionColumn.setBounds(0,0,Math.max(1,width-(wide?314:0)),p.getHeight());questionColumn.doLayout();
            if(wide){indexPanel.setBounds(width-292,0,292,indexPanel.getPreferredSize().height);indexPanel.doLayout();}
        }
    }
    private static final class HeadingLayout implements LayoutManager {
        public void addLayoutComponent(String n,Component c){}public void removeLayoutComponent(Component c){}
        public Dimension minimumLayoutSize(Container p){return new Dimension(0,0);}
        public Dimension preferredLayoutSize(Container p){int width=p.getWidth()>0?p.getWidth():650;Component text=p.getComponent(0);text.setSize(width>=640?Math.max(1,width-252):width,1);int h=text.getPreferredSize().height;Insets in=p.getInsets();return new Dimension(width,(width>=640?Math.max(h,102):h+122)+in.top+in.bottom);}
        public void layoutContainer(Container p){int w=p.getWidth();Insets in=p.getInsets();Component text=p.getComponent(0),stats=p.getComponent(1);text.setSize(w>=640?Math.max(1,w-252):w,1);int h=text.getPreferredSize().height;text.setBounds(0,in.top,text.getWidth(),h);if(text instanceof Container c)c.doLayout();stats.setBounds(w>=640?w-220:0,in.top+(w>=640?Math.max(0,h-102):h+20),w>=640?220:w,102);if(stats instanceof Container c)c.doLayout();}
    }
}
