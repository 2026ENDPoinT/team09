package dev.synesis.poc.ui;

import dev.synesis.poc.planner.PlannerModel;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.swing.*;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.event.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;
import static dev.synesis.poc.ui.PlannerDialogs.*;

/** Monthly Planner · 2026년 11월, rXyo0q7de1KhW5adriY7YU / 2:99. Dates and rows are live user data. */
final class PlannerMonthView extends JPanel {
    static final Color INK=new Color(0x171717),MUTED=new Color(0x7b7b7b),SUBTLE=new Color(0xa5a5a5),WEEKEND_BG=new Color(0xfffafb);
    static final int HEADER_HEIGHT=40,DAY_HEADING=30,EVENT_HEIGHT=20,EVENT_GAP=3,CELL_INSET=6;
    final PlannerDesign planner;
    final Card daily,upcoming,selected=new Card(Color.WHITE,12),todos=new Card(Color.WHITE,12);
    final QuickNote quick=new QuickNote();
    final JLabel title=heading("MONTHLY PLANNER",26),subtitle=label("월간 플래너",12,PlannerStyle.MUTED),error=label("",11,ERROR_COLOR);
    final JLabel dailyDate=label("",10,MUTED),selectedHeading=heading("오늘의 일정",CARD_TITLE_SIZE),selectedDateLabel=label("",12,INK),upcomingCount=label("",11,NAVY);
    final JPanel switcher=new JPanel(null),selectedRows=rows(),todoRows=rows(),filters=new JPanel(new PlannerWeekView.WrapLayout());
    final JScrollPane dailyScroll,selectedScroll=quiet(selectedRows),todoScroll=quiet(todoRows),filterScroll=quiet(filters),upcomingScroll;
    final JButton addTodo,addTodoFooter,addSelected,selectedToday,addUpcoming,allUpcoming,goal;
    LocalDate selectedDate,shownAnchor;
    String tagFilter="";
    private DailyData renderedDaily;
    private TodoData renderedTodos;
    private SelectedData renderedSelected;
    private UpcomingData renderedUpcoming;
    private record DailyData(LocalDate date,List<Task> tasks,boolean readFailed){}
    private record TodoData(LocalDate month,List<MonthlyTask> tasks,List<Tag> tags,String filter,boolean readFailed){}
    private record SelectedData(LocalDate date,LocalDate today,List<Event> events,boolean readFailed){}
    private record UpcomingData(LocalDate today,List<Event> events){}

    PlannerMonthView(PlannerDesign planner){
        super(null);this.planner=planner;selectedDate=planner.anchor;setBackground(Color.WHITE);name(this,"MAIN-플래너_월간");
        daily=planner.tasks;upcoming=planner.upcoming;daily.removeAll();upcoming.removeAll();daily.setLayout(null);upcoming.setLayout(null);selected.setLayout(null);todos.setLayout(null);
        title.setForeground(PlannerStyle.INK);switcher.setOpaque(false);switcher.add(planner.week);switcher.add(planner.month);
        for(JButton b:List.of(planner.week,planner.month))b.setFont(medium(11));planner.week.setBorder(null);planner.week.setBackground(SURFACE);planner.week.setForeground(PlannerStyle.MUTED);
        planner.range.setFont(regular(15));planner.range.setForeground(PlannerStyle.INK);
        planner.bell.setDisabledIcon(planner.bell.getIcon());planner.bell.setBorder(null);
        for(Component c:List.of(title,subtitle,switcher,planner.add,planner.bell,planner.range,planner.previous,planner.today,planner.next,error,daily,quick,selected,todos,upcoming))add(c);
        planner.status.addPropertyChangeListener("text",e->error.setText(planner.status.getText()));error.addMouseListener(new MouseAdapter(){public void mouseClicked(MouseEvent e){planner.reload();}});error.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        daily.add(heading("오늘의 TODO",CARD_TITLE_SIZE));daily.add(dailyDate);
        planner.previousTaskDay.setIcon(asset("daily-left",12));planner.nextTaskDay.setIcon(asset("daily-right",12));
        daily.add(planner.previousTaskDay);daily.add(planner.nextTaskDay);dailyScroll=quiet(planner.taskRows);daily.add(dailyScroll);
        styleLink(planner.addTask,10,MUTED);planner.addTask.setText("+  새로운 TODO 생성");daily.add(planner.addTask);
        selected.add(selectedHeading);selected.add(selectedDateLabel);
        selectedToday=link("오늘",10,NAVY,()->selectDate(LocalDate.now(planner.clock)));selectedToday.setBackground(SURFACE);selectedToday.setHorizontalAlignment(SwingConstants.CENTER);selected.add(selectedToday);selected.add(selectedScroll);
        addSelected=link("+  이 날짜에 일정 추가",10,NAVY,()->planner.editEvent(null,selectedDate.atTime(10,0)));selected.add(addSelected);
        todos.add(heading("이번 달 TODO",CARD_TITLE_SIZE));addTodo=assetButton("plus","이번 달 TODO 생성",16,()->editTodo(null));todos.add(addTodo);filters.setOpaque(false);((FadeScrollPane)filterScroll).setVerticalOverflowShadowHeight(10);todos.add(filterScroll);todos.add(todoScroll);
        addTodoFooter=link("+  새로운 TODO 생성",10,MUTED,()->editTodo(null));todos.add(addTodoFooter);
        upcoming.add(heading("다가오는 일정",CARD_TITLE_SIZE));upcoming.add(upcomingCount);addUpcoming=assetButton("plus","중요 일정 추가",16,this::addImportant);upcoming.add(addUpcoming);
        upcomingScroll=quiet(planner.upcomingRows);upcoming.add(upcomingScroll);upcoming.add(label("가까운 날짜순",9,MUTED));
        allUpcoming=link("전체 보기  ›",10,NAVY,this::showUpcoming);allUpcoming.setHorizontalAlignment(SwingConstants.RIGHT);upcoming.add(allUpcoming);
        goal=link("이번 달 목표",11,MUTED,planner::editGoal);selected.add(goal);
    }
    static JPanel rows(){JPanel p=new Rows();p.setLayout(new BoxLayout(p,BoxLayout.Y_AXIS));p.setOpaque(false);return p;}
    static final class Rows extends JPanel implements Scrollable {
        @Override public Dimension getPreferredScrollableViewportSize(){return getPreferredSize();}
        @Override public int getScrollableUnitIncrement(Rectangle r,int orientation,int direction){return ScrollPolicy.PIXELS_PER_UNIT;}
        @Override public int getScrollableBlockIncrement(Rectangle r,int orientation,int direction){return Math.max(24,r.height-24);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}
    }
    static JScrollPane quiet(Component view){
        FadeScrollPane pane=new FadeScrollPane(view,JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
        pane.setBorder(null);pane.setBackground(Color.WHITE);pane.getViewport().setBackground(Color.WHITE);
        pane.setVerticalOverflowShadowHeight(20);pane.setVerticalOverflowShadow(true);
        pane.setScrollCacheEnabled(true);
        pane.getVerticalScrollBar().setPreferredSize(new Dimension(3,0));pane.getVerticalScrollBar().setUI(new FadingScrollBarUI(NAVY,.20f));return pane;
    }
    static Icon asset(String id,int size){return icon("monthly/"+id,size);}
    static JButton assetButton(String id,String name,int size,Runnable action){JButton b=link("",10,MUTED,action);b.setIcon(asset(id,size));name(b,name);return b;}
    static void styleLink(JButton b,int size,Color color){b.setBorder(null);b.setFont(regular(size));b.setForeground(color);b.setHorizontalAlignment(SwingConstants.LEFT);}
    static JButton link(String text,int size,Color color,Runnable action){JButton b=button(text,false,action);styleLink(b,size,color);return b;}
    void writeEnabled(boolean enabled){
        for(JButton b:List.of(planner.add,planner.addTask,addSelected,addTodo,addTodoFooter,addUpcoming,goal))b.setEnabled(enabled);
        for(JPanel rows:List.of(planner.taskRows,todoRows))for(Component child:rows.getComponents())if(child instanceof TodoRow row){row.check.setEnabled(enabled);row.edit.setEnabled(enabled);}
    }
    void refresh(){
        if(planner.calendar.getParent()!=this){add(planner.calendar);revalidate();}
        if(shownAnchor==null||!shownAnchor.equals(planner.anchor)){
            if(!YearMonth.from(selectedDate).equals(YearMonth.from(planner.anchor)))selectedDate=planner.anchor;
            shownAnchor=planner.anchor;
        }
        planner.range.setText(planner.anchor.format(DateTimeFormatter.ofPattern("uuuu년 M월")));
        planner.week.setBackground(SURFACE);planner.week.setForeground(PlannerStyle.MUTED);planner.month.setBackground(NAVY);planner.month.setForeground(Color.WHITE);
        refreshDaily();renderSelected();renderTodos();renderUpcoming();writeEnabled(!planner.readFailed);
    }
    void selectDate(LocalDate date){
        ScrollCacheViewport.invalidateContent(this);
        LocalDate previous=selectedDate;
        selectedDate=date;planner.taskDate=date;
        if(!YearMonth.from(date).equals(YearMonth.from(planner.anchor)))planner.anchor=date;
        planner.refresh();renderSelected();refreshDaily();
        if(planner.calendar.getComponent(0) instanceof PlannerCalendar calendar
                &&calendar.getComponent(0) instanceof PlannerCalendar.Month month){month.repaintDate(previous);month.repaintDate(date);}
    }
    void refreshDaily(){
        List<Task> tasks=planner.state.tasks().stream().filter(t->t.date().equals(planner.taskDate)).toList();DailyData data=new DailyData(planner.taskDate,tasks,planner.readFailed);
        if(data.equals(renderedDaily))return;renderedDaily=data;dailyDate.setText(planner.taskDate.format(DateTimeFormatter.ofPattern("M월 d일 (E)",Locale.KOREAN)));planner.taskHeading.setText((planner.taskDate.equals(LocalDate.now(planner.clock))?"오늘 · ":"")+dailyDate.getText());planner.taskCount.setText(tasks.stream().filter(Task::completed).count()+" / "+tasks.size()+"개 완료");planner.taskRows.removeAll();
        for(Task task:tasks)planner.taskRows.add(new TodoRow(task.title(),"",task.completed(),38,()->planner.save(()->planner.store.toggleTask(task.id())),()->planner.editTask(task)));
        if(tasks.isEmpty())planner.taskRows.add(empty("오늘 하고 싶은 일을 적어보세요."));planner.taskRows.revalidate();planner.taskRows.repaint();
    }
    void renderSelected(){
        LocalDate today=LocalDate.now(planner.clock);SelectedData data=new SelectedData(selectedDate,today,planner.state.events(),planner.readFailed);
        if(data.equals(renderedSelected))return;renderedSelected=data;selectedHeading.setText(selectedDate.equals(today)?"오늘의 일정":"선택한 날짜의 일정");selectedDateLabel.setText(selectedDate.format(DateTimeFormatter.ofPattern("M월 d일 EEEE",Locale.KOREAN)));
        selectedRows.removeAll();List<Occurrence> values=occurrences(planner.state,selectedDate,selectedDate.plusDays(1));
        for(Occurrence o:values){JButton b=eventButton(o,true,()->planner.editEvent(o.event(),o.start()));b.setPreferredSize(new Dimension(264,44));b.setMaximumSize(new Dimension(Integer.MAX_VALUE,44));selectedRows.add(b);selectedRows.add(Box.createVerticalStrut(10));}
        if(values.isEmpty())selectedRows.add(empty("등록한 일정이 없어요."));selectedRows.revalidate();selectedRows.repaint();
    }
    List<MonthlyTask> monthTasks(){LocalDate month=planner.anchor.withDayOfMonth(1);return planner.state.monthlyTasks().stream().filter(t->t.month().equals(month)).toList();}
    void renderTodos(){
        List<MonthlyTask> values=monthTasks();Map<String,Integer> counts=new HashMap<>();for(MonthlyTask t:values)for(String tag:t.tagIds())counts.merge(tag,1,Integer::sum);
        if(counts.getOrDefault(tagFilter,0)==0||planner.state.todoTags().stream().noneMatch(t->t.id().equals(tagFilter)))tagFilter="";
        TodoData data=new TodoData(planner.anchor.withDayOfMonth(1),values,planner.state.todoTags(),tagFilter,planner.readFailed);if(data.equals(renderedTodos))return;renderedTodos=data;
        filters.removeAll();filters.add(filter("전체 "+values.size(),""));for(Tag t:planner.state.todoTags())if(counts.getOrDefault(t.id(),0)>0)filters.add(filter(t.name()+" "+counts.get(t.id()),t.id()));
        todoRows.removeAll();for(MonthlyTask t:values)if(tagFilter.isEmpty()||t.tagIds().contains(tagFilter))todoRows.add(new TodoRow(t.title(),t.completed()||t.deadline()==null?"":t.deadline().format(DateTimeFormatter.ofPattern("MM.dd")),t.completed(),t.completed()||t.deadline()==null?26:36,()->planner.save(()->planner.store.toggleMonthlyTask(t.id())),()->editTodo(t)));
        if(todoRows.getComponentCount()==0)todoRows.add(empty("이번 달 TODO를 추가해 보세요."));filters.revalidate();todoRows.revalidate();todos.revalidate();todos.repaint();
    }
    JButton filter(String text,String id){JButton b=button(text,id.equals(tagFilter),()->{tagFilter=id;renderTodos();});b.setFont(medium(10));b.setBorder(null);b.setBackground(id.equals(tagFilter)?NAVY:SURFACE);b.setForeground(id.equals(tagFilter)?Color.WHITE:MUTED);b.setPreferredSize(new Dimension(Math.min(180,Math.max(54,b.getPreferredSize().width)),25));return b;}
    void editTodo(MonthlyTask task){if(!planner.readFailed)showDialog(this,PlannerWeekEditors.Todo.monthly(planner,task),task==null?"이번 달 TODO 생성":"이번 달 TODO 편집",480,560);}
    List<Occurrence> upcomingEvents(){LocalDate today=LocalDate.now(planner.clock);return occurrences(planner.state,today,today.plusDays(366)).stream().filter(o->o.event().important()&&!o.start().toLocalDate().isBefore(today)).toList();}
    void renderUpcoming(){UpcomingData data=new UpcomingData(LocalDate.now(planner.clock),planner.state.events());if(data.equals(renderedUpcoming))return;renderedUpcoming=data;
        List<Occurrence> values=upcomingEvents();upcomingCount.setText(Integer.toString(values.size()));planner.upcomingRows.removeAll();
        for(Occurrence o:values){planner.upcomingRows.add(new DDayRow(o));planner.upcomingRows.add(Box.createVerticalStrut(8));}
        if(values.isEmpty())planner.upcomingRows.add(empty("중요 일정의 디데이가 여기에 표시돼요."));planner.upcomingRows.revalidate();planner.upcomingRows.repaint();
    }
    void addImportant(){if(planner.readFailed)return;EventEditor editor=new EventEditor(planner.store,planner.state,null,selectedDate.atTime(10,0),planner::accept,planner.clock);editor.important.setSelected(true);showDialog(this,editor,"중요 일정 추가",920,804);}
    void showUpcoming(){
        JPanel panel=new ModalPanel(new BorderLayout(12,16));panel.setBackground(Color.WHITE);panel.setBorder(BorderFactory.createEmptyBorder(24,24,24,24));panel.putClientProperty("planner.backdropDismiss",true);
        panel.add(heading("다가오는 중요 일정 · 1년",18),BorderLayout.NORTH);JPanel list=rows();for(Occurrence o:upcomingEvents()){DDayRow row=new DDayRow(o,()->{close(panel);SwingUtilities.invokeLater(()->planner.editEvent(o.event(),o.start()));});list.add(row);list.add(Box.createVerticalStrut(8));}
        if(list.getComponentCount()==0)list.add(empty("다가오는 중요 일정이 없어요."));panel.add(quiet(list));JPanel footer=PlannerDesign.actions();footer.add(button("닫기",false,()->requestClose(panel)));panel.add(footer,BorderLayout.SOUTH);showDialog(this,panel,"다가오는 일정",460,620);
    }
    int minimumHeight(int width){int pad=width<900?16:28,w=width-pad*2;return PlannerWeekView.headerBodyY(width)+Math.max(720,40+calendarRows()*68+184)+pad+(w<700?848+16:0)+(w<500?184:0);}
    int calendarRows(){LocalDate day=planner.anchor.withDayOfMonth(1);return (day.getDayOfWeek().getValue()-1+day.lengthOfMonth()+6)/7;}
    @Override public void doLayout(){
        int pad=getWidth()<900?16:28,w=Math.max(1,getWidth()-pad*2),gap=w<700?16:20;boolean stack=w<700;
        int bodyY=PlannerWeekView.layoutHeader(getWidth(),planner.anchor,title,subtitle,planner.range,error,planner.previous,planner.today,planner.next,planner.add,planner.week,planner.month,planner.bell,switcher);
        int side=stack?w:Math.min(296,Math.max(240,Math.round(w*296/1494f))),left=stack?w:w-side-gap;
        int bodyH=Math.max(720,getHeight()-bodyY-pad-(stack?864:0)-(w<500?184:0)),bottom=168,calendarH=bodyH-bottom-16;
        planner.calendar.setBounds(pad,bodyY,left,calendarH);int bottomY=bodyY+calendarH+16;
        if(w>=500){int dailyW=Math.round((left-16)*450/1162f);daily.setBounds(pad,bottomY,dailyW,bottom);quick.setBounds(pad+dailyW+16,bottomY,left-dailyW-16,bottom);}else{daily.setBounds(pad,bottomY,left,bottom);quick.setBounds(pad,bottomY+184,left,bottom);}
        int sideX=stack?pad:pad+left+gap,sideY=stack?quick.getY()+quick.getHeight()+16:bodyY,sideH=stack?848:bodyH;
        int selectedH=Math.round(sideH*238/848f),todoH=Math.round(sideH*300/848f);selected.setBounds(sideX,sideY,side,selectedH);todos.setBounds(sideX,sideY+selectedH+16,side,todoH);upcoming.setBounds(sideX,todos.getY()+todoH+16,side,sideH-selectedH-todoH-32);
        layoutDaily();layoutSelected();layoutTodos();layoutUpcoming();
    }
    void layoutDaily(){int w=daily.getWidth(),h=daily.getHeight();daily.getComponent(0).setBounds(17,17,110,26);dailyDate.setBounds(Math.max(122,w-119),22,64,18);dailyDate.setVisible(w>=280);planner.previousTaskDay.setBounds(w-52,20,20,20);planner.nextTaskDay.setBounds(w-28,20,20,20);dailyScroll.setBounds(17,53,Math.max(1,w-34),Math.max(1,h-92));planner.addTask.setBounds(17,h-39,Math.max(1,w-34),20);}
    void layoutSelected(){int w=selected.getWidth(),h=selected.getHeight();selectedHeading.setBounds(17,17,w-120,26);goal.setBounds(w-97,20,80,22);selectedDateLabel.setBounds(17,53,w-90,24);selectedToday.setBounds(w-55,53,38,25);selectedScroll.setBounds(17,87,w-34,Math.max(1,h-138));addSelected.setBounds(17,h-49,w-34,28);}
    void layoutTodos(){int w=todos.getWidth(),h=todos.getHeight();todos.getComponent(0).setBounds(17,17,w-60,26);addTodo.setBounds(w-41,21,24,20);int fh=Math.min(60,Math.max(25,((PlannerWeekView.WrapLayout)filters.getLayout()).height(filters,w-34)));filterScroll.setBounds(17,55,w-34,fh);int top=55+fh+12;todoScroll.setBounds(17,top,w-34,Math.max(1,h-top-48));addTodoFooter.setBounds(17,h-42,w-34,24);}
    void layoutUpcoming(){int w=upcoming.getWidth(),h=upcoming.getHeight();upcoming.getComponent(0).setBounds(17,17,98,26);upcomingCount.setBounds(115,22,48,18);addUpcoming.setBounds(w-41,21,24,20);upcomingScroll.setBounds(17,53,w-34,Math.max(1,h-94));upcoming.getComponent(4).setBounds(17,h-31,100,16);allUpcoming.setBounds(w-107,h-33,90,20);}
    static JLabel empty(String text){JLabel l=label(text,11,MUTED);l.setBorder(BorderFactory.createEmptyBorder(5,0,5,0));return l;}
    static JButton eventButton(Occurrence o,boolean detail,Runnable action){
        JButton b=link("",11,INK,action);b.setUI(new BasicButtonUI(){@Override public void paint(Graphics g,JComponent c){paintEvent((Graphics2D)g,c.getWidth(),c.getHeight(),o,detail,false,false);}});b.setBorder(null);b.setOpaque(false);b.setContentAreaFilled(false);name(b,o.event().title()+" · "+o.start()+" ~ "+o.end());b.setToolTipText(b.getName());b.addFocusListener(new FocusAdapter(){@Override public void focusGained(FocusEvent e){b.scrollRectToVisible(new Rectangle(0,0,b.getWidth(),b.getHeight()));}});return b;
    }
    static void paintEvent(Graphics2D graphics,int width,int height,Occurrence o,boolean detail,boolean continuation,boolean continues){
        Graphics2D g=quality(graphics);g.clipRect(0,0,width,height);Color color=new Color(o.event().color().rgb);int inset=continuation?-5:0;
        PlannerEventCard.surface(g,inset,0,width+(continuation?5:0)+(continues?5:0),height,color,4);
        String time=o.event().allDay()?"":o.start().format(DateTimeFormatter.ofPattern("HH:mm"))+(detail?"–"+o.end().format(DateTimeFormatter.ofPattern("HH:mm")):"");
        Font tf=regular(detail?10:9);int timeWidth=time.isEmpty()?0:g.getFontMetrics(tf).stringWidth(time);int left=detail?11:10;
        PlannerWeekCalendarSkin.line(g,o.event().title(),medium(detail?12:11),INK,left,0,Math.max(1,width-left-timeWidth-(timeWidth>0?10:6)),height);
        if(timeWidth>0)PlannerWeekCalendarSkin.line(g,time,tf,MUTED,width-6-timeWidth,0,timeWidth,height);g.dispose();
    }
    final class TodoRow extends JPanel {
        final JCheckBox check;final JButton edit;final JLabel deadline;final int height;
        TodoRow(String text,String date,boolean completed,int height,Runnable toggle,Runnable open){
            super(null);this.height=height;setOpaque(false);setPreferredSize(new Dimension(264,height));setMaximumSize(new Dimension(Integer.MAX_VALUE,height));
            check=PlannerWeekView.todoCheck();check.setSelectedIcon(new Icon(){public int getIconWidth(){return 14;}public int getIconHeight(){return 14;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=quality(graphics);g.setColor(NAVY);g.fillRoundRect(x,y,14,14,8,8);asset("completed-check",10).paintIcon(c,g,x+2,y+2);g.dispose();}});check.setSelected(completed);check.setEnabled(!planner.readFailed);name(check,text+" 완료");check.addActionListener(e->toggle.run());add(check);
            edit=link(text,11,completed?SUBTLE:INK,open);edit.setEnabled(!planner.readFailed);if(completed)edit.setFont(edit.getFont().deriveFont(Map.of(java.awt.font.TextAttribute.STRIKETHROUGH,java.awt.font.TextAttribute.STRIKETHROUGH_ON)));name(edit,text+" 편집");add(edit);deadline=label(date,9,SUBTLE);add(deadline);
        }
        @Override public void doLayout(){int y=height==38?7:2;check.setBounds(0,y,14,16);edit.setBounds(23,y-2,Math.max(1,getWidth()-23),22);deadline.setBounds(0,21,getWidth(),14);}
    }
    final class DDayRow extends JButton {
        final Occurrence occurrence;
        DDayRow(Occurrence o){this(o,()->planner.editEvent(o.event(),o.start()));}
        DDayRow(Occurrence o,Runnable open){occurrence=o;setUI(new BasicButtonUI());setBorder(null);setContentAreaFilled(false);setOpaque(false);setFocusPainted(false);setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));setPreferredSize(new Dimension(254,56));setMaximumSize(new Dimension(Integer.MAX_VALUE,56));name(this,o.event().title()+" · "+dDay(LocalDate.now(planner.clock),o.start().toLocalDate()));addActionListener(e->open.run());}
        @Override protected void paintComponent(Graphics graphics){Graphics2D g=quality(graphics);g.setColor(SURFACE);g.fillRoundRect(0,0,getWidth(),getHeight(),14,14);String day=dDay(LocalDate.now(planner.clock),occurrence.start().toLocalDate());int dayW=Math.min(96,Math.max(70,getWidth()*88/254));
            PlannerWeekCalendarSkin.line(g,day,bold(day.length()>5?22:30),NAVY,10,6,dayW,44);int x=dayW+18,w=getWidth()-x-8;
            PlannerWeekCalendarSkin.line(g,occurrence.event().title(),medium(11),INK,x,10,w,15);LocalDate start=occurrence.start().toLocalDate(),end=occurrence.end().minusNanos(1).toLocalDate();String date=start.format(DateTimeFormatter.ofPattern("M월 d일 (E)",Locale.KOREAN))+(end.isAfter(start)?" – "+end.format(DateTimeFormatter.ofPattern(YearMonth.from(start).equals(YearMonth.from(end))?"d일 (E)":"M월 d일 (E)",Locale.KOREAN)):"");PlannerWeekCalendarSkin.line(g,date,regular(9),MUTED,x,28,w,13);g.dispose();}
    }
    @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);Graphics2D g=quality(graphics);g.setColor(SURFACE);Rectangle r=switcher.getBounds();g.fillRoundRect(r.x,r.y,r.width,r.height,16,16);g.dispose();}
    static final class QuickNote extends Card {
        QuickNote(){super(Color.WHITE,12);name(this,"Quick Note 디자인 미리보기 · 편집 및 저장 미지원");}
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Graphics2D g=quality(graphics);int split=Math.max(120,Math.round(getWidth()*218/712f)),right=split+1;g.setColor(SURFACE);g.fillRect(1,1,split,getHeight()-2);
            drawText(g,"Quick Note",bold(CARD_TITLE_SIZE),INK,13,13,split-40);asset("plus",16).paintIcon(this,g,split-27,18);
            String[] notes={"Synesis PDF 모듈","전시 감상 에세이","금융의 이해 요약"};for(int i=0;i<3;i++){int y=47+i*36;if(i==0){g.setColor(new Color(0xe9f0f9));g.fillRoundRect(13,y,split-24,28,10,10);}asset(i==0?"list-selected":"list",12).paintIcon(this,g,21,y+8);drawText(g,notes[i],regular(10),i==0?NAVY:MUTED,41,y+6,split-46);}
            int x=right+16,w=Math.max(1,getWidth()-x-16);drawText(g,"Synesis PDF 모듈",bold(14),INK,x,15,w-52);asset("arrow",14).paintIcon(this,g,getWidth()-55,21);asset("more",16).paintIcon(this,g,getWidth()-31,20);
            drawText(g,"본문",regular(9),MUTED,x,48,22);drawText(g,"⌄     B    I    ☷",new Font(Font.DIALOG,Font.PLAIN,9),MUTED,x+23,48,w-23);drawText(g,"이번 달 구현할 기능",medium(10),INK,x,69,w);drawText(g,"• PDF 업로드와 미리보기 흐름 정리",regular(10),MUTED,x,91,w);drawText(g,"• 문서별 학습 메모 연결",regular(10),MUTED,x,106,w);
            drawText(g,"자동 저장됨",regular(8),SUBTLE,x,128,w-80);drawText(g,"11월 2일 수정",regular(8),SUBTLE,getWidth()-63,128,54);g.dispose();
        }
    }
}
