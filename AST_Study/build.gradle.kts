plugins {
    application
    java
}

repositories {
    mavenCentral()
}

val os = System.getProperty("os.name").lowercase()
dependencies {
    implementation("org.apache.pdfbox:pdfbox:3.0.8")
    implementation("com.google.code.gson:gson:2.13.2")
    implementation("org.commonmark:commonmark:0.30.0")
    implementation("org.commonmark:commonmark-ext-gfm-tables:0.30.0")
    implementation("org.scilab.forge:jlatexmath:1.0.7")
}

application {
    mainClass = "dev.synesis.poc.AstStudyMain"
}

tasks.named<JavaExec>("run") {
    jvmArgs("-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8")
    if (os.contains("mac")) jvmArgs("-Xdock:name=AST Study")
}

if (os.contains("mac")) {
    // Native fullscreen completion events let Swing refresh layouts after the title bar disappears.
    tasks.withType<JavaExec>().configureEach {
        jvmArgs("--add-exports=java.desktop/com.apple.eawt=ALL-UNNAMED")
    }
}

java {
    toolchain.languageVersion = JavaLanguageVersion.of(21)
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}

tasks.register<JavaExec>("pdfSmokeTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.PdfSmokeTest"
    if (providers.gradleProperty("pdfFixturesOnly").isPresent) args("--fixtures")
    if (providers.gradleProperty("summaryNumberingOnly").isPresent) args("--summary-numbering")
}

tasks.register<JavaExec>("pdfReflowTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.PdfReflowTest"
}

tasks.register<JavaExec>("lectureGenerationUiTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.StudyGenerationUiTest"
}

tasks.register<JavaExec>("studyMarkdownTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.StudyMarkdownTest"
}

// A local CPU baseline for UI changes; this does not claim native Windows screen FPS.
tasks.register<JavaExec>("uiPaintBenchmark") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.ui.UiPaintBenchmark"
    jvmArgs("-Djava.awt.headless=true")
    args(providers.gradleProperty("uiBenchmarkDir").getOrElse("build/ui-paint-benchmark"))
}

tasks.register<JavaExec>("studyMathCorpusTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.StudyMathCorpusTest"
    args(providers.gradleProperty("studyResult").getOrElse("build/new-concept-ver.02-20261011/runs/new-concept-v02-release/result.json"),
        providers.gradleProperty("mathAuditDir").getOrElse("build/ver02-default-20261011/math-audit"))
}

// Offline semantic strategy switching, rollback and streaming preview contracts.
tasks.register<JavaExec>("pdfSemanticTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.PdfSmokeTest"
    args("--semantic")
}

tasks.register<JavaExec>("pdfBatchQueueTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.PdfBatchQueueTest"
}

// Quiz setup, answer comparison and tutor handoff without a window or provider calls.
tasks.register<JavaExec>("quizUiTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.QuizUiTest"
    jvmArgs("-Djava.awt.headless=true")
}

tasks.register<JavaExec>("quizGenerationDataTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.QuizGenerationDataTest"
    jvmArgs("-Djava.awt.headless=true")
}

tasks.register<JavaExec>("quizWorkbookStoreTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.pdf.QuizWorkbookStoreTest"
    jvmArgs("-Djava.awt.headless=true")
}

tasks.register<JavaExec>("astStudySmokeTest") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.synesis.poc.AstStudySmokeTest"
    environment.remove("OPENAI_API_KEY")
}
