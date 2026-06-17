# 《AI大模型Ragent项目》——知识库文件上传大小限制原理

> 看之前觉得「上传文件嘛，有什么好讲的」，看之后发现水还挺深的同学，评论区扣个 **1**，让我知道这篇没白写。

你在 Spring Boot 项目里配置了文件上传大小限制：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                spring:
  servlet:
    multipart:
      max-file-size: 50MB
      max-request-size: 100MB

```

然后你开始担心：如果用户上传一个 1GB 的文件，Spring Boot 会不会先把这 1GB 全部读到内存里，然后才检查大小超限并拒绝？如果是这样，恶意用户可以通过上传超大文件来耗尽服务器内存，导致 OOM（Out of Memory）。

这个担心看起来很合理，但实际上是多余的。Spring Boot 和底层的 Servlet 容器（Tomcat）有完善的早期拒绝机制，超限文件不会被读取到内存。这篇文档就是要从底层原理出发，结合源码和实际测试，讲清楚 Spring Boot 到底是怎么处理文件上传和大小限制的。

## 常见误解：文件上传是先读后检查吗

### 1. 误解的由来

很多开发者的直觉是：文件上传 = 把文件全部读到内存 → 检查大小 → 保存或拒绝。这个直觉在小文件场景下没问题，一个 2MB 的图片上传，读到内存、检查大小、保存到磁盘，整个流程很快，内存占用也不高。

但把这个直觉放大到 GB 级别的文件，问题就来了。假设用户上传一个 1GB 的视频，如果 Spring Boot 真的是先读后检查，那服务器要先分配 1GB 内存把文件读进来，然后才发现超过了 50MB 的限制，再把这 1GB 内存释放掉。如果同时有 10 个用户这么干，服务器就要分配 10GB 内存，很容易 OOM。

### 2. 如果真是这样会怎样

假设 Spring Boot 真的是先读后检查，恶意用户可以这样攻击你的服务器：

- 1.
写一个脚本，循环上传 1GB 的文件

- 2.
每次上传都会占用 1GB 内存

- 3.
并发 10 个请求，服务器内存瞬间被占满

- 4.
服务器 OOM，其他正常用户的请求也无法处理

这是一个严重的安全问题，如果 Spring Boot 真的这么设计，那它就不适合用在生产环境了。

### 3. 实际情况是什么

提前剧透：Spring Boot 和 Servlet 容器（Tomcat）有完善的早期拒绝机制，超限文件不会被读取到内存。具体来说：

- **Tomcat 层**：在解析 HTTP 请求时，会先检查请求头里的 `Content-Length`，如果超过限制，直接拒绝，不会读取请求体（body）

- **Spring Boot 层**：在解析 multipart 请求时，会边读边检查，一旦发现超限，立即停止读取并抛出异常

- **流式处理**：即使文件没超限，Spring Boot 也不会把整个文件加载到内存，而是边读边写到临时文件

接下来咱们从 HTTP 协议、Tomcat 源码、Spring Boot 配置三个层面，把这个机制讲清楚。

## HTTP multipart/form-data 协议基础

### 1. 文件上传请求的关键：Content-Length

文件上传用的是 `multipart/form-data` 协议。对于理解大小限制机制，最关键的是 `Content-Length` 请求头。

一个文件上传请求的请求头长这样：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                POST /upload HTTP/1.1
Host: example.com
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Length: 52428800

```

**关键点：`Content-Length: 52428800`**

这个请求头告诉服务器：整个请求体的大小是 52428800 字节（50MB）。注意：

- 这个值是客户端（浏览器或工具）在发送请求之前就计算好的

- 服务器在读取请求体之前，就能从请求头拿到这个值

- 这是早期拒绝机制的基础

### 2. 为什么 Content-Length 是关键

打个比方，你去快递站寄包裹：

- **传统方式**：快递员先把包裹搬进仓库，称重，发现超重，再搬出来退给你

- **Content-Length 方式**：包裹上贴着重量标签，快递员看一眼标签，发现超重，直接拒收，不用搬进仓库

`Content-Length` 就是这个"重量标签"。服务器在读取请求体（文件内容）之前，就能知道请求有多大，从而决定是接收还是拒绝。

**这就是为什么上传 1GB 文件不会占用 1GB 内存**：服务器看到 `Content-Length: 1GB`，发现超过限制，直接拒绝返回 HTTP 状态码 403，根本不会开始读取文件内容。

### 3. 超出大小后报错明细

大家可能好奇，想着自己测试下超出限制大小报什么错。结果一看不对，返回的明明是下面的 json ，并且状态码是 200。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                {
    "code": "A000001",
    "message": "上传文件大小超过限制，单个文件最大允许 50MB",
    "data": null,
    "requestId": null,
    "success": false
}

```

这是因为咱们在全局异常拦截器里捕获了相关异常，报错信息就是上面那个拦截异常返回的。即使去掉，还有下面那个全局异常拦截。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                /**
 * 拦截文件上传大小超限异常
 */
@ExceptionHandler(value = MaxUploadSizeExceededException.class)
public Result<Void> maxUploadSizeExceededException(HttpServletRequest request, MaxUploadSizeExceededException ex) {
    log.warn("[{}] {} [upload] 文件上传大小超限: {}", request.getMethod(), getUrl(request), ex.getMessage());
    String message;
    if (ex.getCause() instanceof IllegalStateException
            && ex.getCause().getCause() instanceof FileSizeLimitExceededException) {
        message = "上传文件大小超过限制，单个文件最大允许 " + maxFileSize;
    } else {
        message = "上传请求大小超过限制，单次请求最大允许 " + maxRequestSize;
    }
    return Results.failure(BaseErrorCode.CLIENT_ERROR.code(), message);
}

/**
 * 拦截未捕获异常
 */
@ExceptionHandler(value = Throwable.class)
public Result<Void> defaultErrorHandler(HttpServletRequest request, Throwable throwable) {
    log.error("[{}] {} ", request.getMethod(), getUrl(request), throwable);
    return Results.failure();
}

```

如果把这两个都删除，就会遇到下面截图的效果：

![无法获取该图片](assets/39-01.png)

## Servlet 容器（Tomcat）的处理流程

### 1. Tomcat 接收请求的完整流程

Spring Boot 默认使用 Tomcat 作为 Servlet 容器。当用户上传文件时，请求的处理流程是这样的：

![无法获取该图片](assets/39-02.png)

关键点：Tomcat 在解析请求头时，就能拿到 `Content-Length`，如果超过限制，直接拒绝，不会读取请求体。

### 2. 源码分析：Tomcat 如何处理超限请求

#### 2.1 关键源码位置

Tomcat 处理请求体大小限制的核心代码在 `org.apache.coyote.Request` 类中。你可以在 Tomcat 的 GitHub 仓库找到这个类：

[https://github.com/apache/tomcat/blob/main/java/org/apache/coyote/Request.java](https://github.com/apache/tomcat/blob/main/java/org/apache/coyote/Request.java)

#### 2.2 核心逻辑解读

Tomcat 10.1.34（Ragent 使用的版本，对应 Spring Boot 3.5.7）在处理请求时，会在多个层次检查请求大小。核心机制涉及 `org.apache.coyote.Request` 和 `org.apache.catalina.connector.Request` 等类。

下面是简化的逻辑示意（非精确源码，用于说明原理）：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                // 简化示意：Tomcat 请求处理逻辑
public void processRequest() throws IOException {
    // 1. 解析请求头，获取 Content-Length
    long contentLength = getContentLengthLong();

    // 2. 检查是否超过 maxSwallowSize
    if (contentLength > connector.getMaxSwallowSize()) {
        // 设置 413 错误状态
        response.setStatus(HttpServletResponse.SC_REQUEST_ENTITY_TOO_LARGE);
        // 不读取请求体，直接返回
        return;
    }

    // 3. 正常情况下，流式读取请求体
    // 实际实现中会边读边写到临时文件或内存缓冲区
    inputBuffer.doRead(handler);
}

```

> **说明**：上述代码是简化示意，实际 Tomcat 源码更复杂，涉及多个类和方法的协作。完整实现可以查看 Tomcat 10.1.34 的源码：[https://github.com/apache/tomcat/tree/10.1.34](https://github.com/apache/tomcat/tree/10.1.34)

关键点：

- 1.
`getContentLengthLong()` 从请求头获取 `Content-Length`，这个操作不需要读取请求体

- 2.
如果 `Content-Length` 超过 `maxSwallowSize`，Tomcat 会拒绝处理，不读取请求体

- 3.
正常情况下，Tomcat 使用流式处理，边读边写到临时文件，不会一次性加载到内存

#### 2.3 早期拒绝的触发条件

Tomcat 的早期拒绝机制会在以下情况触发：

- **请求体实际大小超过声明值**：如果客户端声明 `Content-Length: 1MB`，但实际发送了 2MB，Tomcat 会在读取到 1MB 后断开连接

- **连接超时**：如果客户端发送请求体的速度太慢，Tomcat 会超时断开连接

> *这里还有一个* `maxSwallowSize` 的概念值得了解：当上传超限时，Tomcat 是直接断开连接（客户端只能看到 Connection reset），还是先把请求体读完再返回一个明确的错误响应，取决于这个配置。感兴趣的同学可以自行查阅。

## Spring Boot 的 multipart 处理机制

### 1. multipart 相关配置

Spring Boot 提供了两个配置来限制上传文件的大小：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                spring:
  servlet:
    multipart:
      max-file-size: 50MB      # 单个文件最大 50MB
      max-request-size: 100MB  # 整个请求最大 100MB

```

这两个配置的区别：

- `max-file-size`：单个文件的大小限制，如果上传多个文件，每个文件都不能超过这个值

- `max-request-size`：整个请求的大小限制，包括所有文件和表单字段的总大小

正常上传流程中，只需要这两个配置就够了。Tomcat 会正常读取请求体，Spring Boot 在解析 multipart 时检查大小，超限则抛出 `MaxUploadSizeExceededException`。

### 2. Spring MVC 的 MultipartResolver

Spring MVC 使用 `MultipartResolver` 来解析 multipart 请求。Spring Boot 默认使用 `StandardServletMultipartResolver`，它基于 Servlet 3.0 的 `Part` API。

解析流程是这样的：

- 1.
Controller 方法接收 `MultipartFile` 参数

- 2.
Spring MVC 调用 `MultipartResolver.resolveMultipart()` 解析请求

- 3.
`StandardServletMultipartResolver` 调用 `HttpServletRequest.getParts()` 获取所有 Part

- 4.
每个 Part 对应一个文件或表单字段

- 5.
Spring MVC 把 Part 包装成 `MultipartFile` 对象，传给 Controller

### 3. 源码分析：Spring 如何处理超限文件

#### 3.1 关键源码位置

Spring Boot 处理 multipart 请求的核心代码在 `org.springframework.web.multipart.support.StandardMultipartHttpServletRequest` 类中。

#### 3.2 核心逻辑解读

Spring Boot 3.5.7（Ragent 使用的版本）在解析 multipart 请求时，会调用 Servlet 容器的 `getParts()` 方法。下面是简化的逻辑示意（非精确源码，用于说明原理）：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                // 简化示意：Spring Boot multipart 解析逻辑
private void parseRequest(HttpServletRequest request) {
    try {
        // 1. 调用 Servlet 容器的 getParts() 方法
        // Tomcat 会流式读取请求体并解析成 Part 对象
        Collection<Part> parts = request.getParts();

        // 2. 遍历每个 Part（文件或表单字段）
        for (Part part : parts) {
            String filename = extractFilename(part.getHeader(CONTENT_DISPOSITION));
            if (filename != null) {
                // 3. 检查单个文件大小
                if (part.getSize() > this.maxFileSize) {
                    throw new MaxUploadSizeExceededException(this.maxFileSize);
                }
                // 4. 包装成 MultipartFile 对象
                this.multipartFiles.add(filename, new StandardMultipartFile(part, filename));
            }
        }
    } catch (IOException | ServletException ex) {
        throw new MultipartException("Failed to parse multipart request", ex);
    }
}

```

> **说明**：上述代码是简化示意，实际 Spring Boot 源码更复杂。完整实现可以查看 Spring Framework 的 `StandardMultipartHttpServletRequest` 类源码。

关键点：

- 1.
`request.getParts()` 是 Servlet 3.0 的标准 API，由 Tomcat 实现

- 2.
Tomcat 在实现 `getParts()` 时，会边读边解析，不会一次性把整个请求体读到内存

- 3.
Spring Boot 拿到每个 Part 后，检查 `part.getSize()`，如果超过 `max-file-size`，抛出 `MaxUploadSizeExceededException`

- 4.
文件内容会被 Tomcat 写入临时文件，内存中只有缓冲区大小的数据

#### 3.3 异常抛出时机

`MaxUploadSizeExceededException` 在什么时候抛出？有两种情况：

- 1.
**整个请求超限**：如果 `Content-Length` 超过 `max-request-size`，Tomcat 在调用 `getParts()` 时就会抛出异常，此时还没开始读取请求体

- 2.
**单个文件超限**：如果单个文件的大小超过 `max-file-size`，Tomcat 在读取该 Part 的过程中发现超限并抛出异常，Spring Boot 将其包装为 `MaxUploadSizeExceededException`

第二种情况看起来像是先读后检查，但实际上 Tomcat 在读取时是流式处理的，文件内容直接写到临时文件，不会占用大量内存。

## 流式处理与临时文件机制

### 1. 即使文件没超限，也不会全部加载到内存

前面讲了超限文件的早期拒绝机制，那没超限的文件呢？比如用户上传一个 30MB 的文件，没超过 50MB 的限制，Spring Boot 会把这 30MB 全部读到内存吗？

答案是不会。Spring Boot 使用流式处理 + 临时文件机制，避免大文件占用内存。

具体流程是这样的：

- 1.
Tomcat 接收到请求后，开始读取请求体

- 2.
读取到的数据先放到一个小的内存缓冲区（默认 8KB）

- 3.
如果文件大小超过内存阈值（默认 0 字节，即所有文件），就把缓冲区的数据写到临时文件

- 4.
继续读取请求体，边读边写到临时文件

- 5.
读取完成后，临时文件包含完整的文件内容

- 6.
Controller 拿到的 `MultipartFile` 对象，底层指向这个临时文件

整个过程中，内存占用只有一个小的缓冲区（8KB），不会因为文件大而占用大量内存。

### 2. Controller 拿到的是引用，不是文件内容

一个常见的误解是：Controller 接收到 `MultipartFile` 参数时，文件内容已经在内存里了。实际上并非如此。`MultipartFile` 只是一个指向磁盘临时文件的引用对象，本身非常轻量。文件内容什么时候进入内存，取决于你在 Controller 里怎么使用它：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                @PostMapping("/upload")
public String upload(@RequestParam("file") MultipartFile file) {
    // 此时 30MB 的文件内容在磁盘临时文件里，不在内存中
    // file 对象本身很小，只是一个包装器
    // ❌ 这样会把 30MB 全部读进内存
    byte[] bytes = file.getBytes();
    // ✅ 这样是流式读取，内存中只有缓冲区大小的数据
    try (InputStream is = file.getInputStream()) {
        // 边读边处理
    }
    // ✅ 这样是文件级别的移动/复制，不经过内存
    file.transferTo(new File("/data/uploads/xxx.pdf"));
}

```

下面用时序图展示从客户端上传到 Controller 使用的完整流程：

![无法获取该图片](assets/39-03.png)

### 2. 临时文件的位置和清理

临时文件存储在哪里？由 `java.io.tmpdir` 系统属性决定，不同操作系统的默认位置不同：

- **Linux**：`/tmp`

- **Windows**：`C:\Users\<用户名>\AppData\Local\Temp`

- **macOS**：`/var/folders/xxx`

你可以通过配置修改临时文件位置：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                spring:
  servlet:
    multipart:
      location: /data/upload-temp  # 自定义临时文件目录

```

临时文件什么时候清理？

- **请求处理完成后自动清理**：Spring Boot 在请求处理完成后，会自动删除临时文件

- **如果你调用了 `MultipartFile.transferTo()`**：文件会被移动到目标位置，临时文件被删除

- **如果请求处理过程中抛出异常**：临时文件也会被清理

### 3. 内存阈值配置

Spring Boot 有一个 `file-size-threshold` 配置，用于控制什么时候把数据写到临时文件：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                spring:
  servlet:
    multipart:
      file-size-threshold: 0  # 默认值，所有文件都写临时文件

```

这个配置的含义：

- `0`：所有文件都写临时文件，不占用内存（默认值，推荐）

- `10KB`：小于 10KB 的文件放内存，大于 10KB 的写临时文件

- `1MB`：小于 1MB 的文件放内存，大于 1MB 的写临时文件

生产环境建议保持默认值 `0`，因为：

- 内存比磁盘贵，能用磁盘就不用内存

- 临时文件的 I/O 性能足够好，不会成为瓶颈

- 避免因为小文件累积导致内存占用过高

## 实战验证：用 Ragent 项目测试

### 1. Ragent 的文件上传配置

Ragent 项目是一个企业级 RAG 智能体平台，有完整的文档上传功能。咱们可以用它来验证文件上传大小限制的机制。

Ragent 的配置文件 `application.yml` 中有这样的配置：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                spring:
  servlet:
    multipart:
      max-file-size: 50MB
      max-request-size: 100MB

```

文件上传接口在 `KnowledgeDocumentController` 中（简化示意，实际代码更复杂）：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
                // 简化示意：Ragent 文件上传接口
@PostMapping("/{kb-id}/docs/upload")
public Result<String> upload(
    @PathVariable("kb-id") String kbId,
    @RequestParam("file") MultipartFile file
) {
    // 检查文件是否为空
    if (file.isEmpty()) {
        throw new ClientException("文件不能为空");
    }

    return Results.success(null);
}

```

> **说明**：上述代码是简化示意，实际 Ragent 的 upload 方法使用 `@RequestPart` 注解、返回完整的 VO 对象，并支持更多参数。这里简化是为了聚焦文件上传大小限制的核心机制。

关键点：无论实际实现多复杂，底层都是通过 `MultipartFile` 接口接收文件，Spring Boot 会在解析 multipart 请求时检查文件大小。

### 2. 测试步骤

前端我做了限制，不允许超过 50 MB，如果想测试更大的 1G 文件，可以直接调用接口上传。

![无法获取该图片](assets/39-04.png)

在标红线的位置，我上传了多次 30 多 MB 的文件，并未出现内存波动，可以证明上述逻辑是正确的。

![无法获取该图片](assets/39-05.png)

### 3. 测试结果分析

如果大家调整下项目的文件限制，通过实际测试，可以验证出：

- 1.
**超限文件不会被全部加载到内存**：上传 100MB 和 1GB 文件时，内存占用没有明显增长

- 2.
**早期拒绝机制确实生效**：超限文件在几毫秒内被拒绝，说明服务器没有读取完整的文件内容

- 3.
**流式处理机制确实生效**：未超限文件通过临时文件处理，内存占用只有一个小的缓冲区

## 常见问题解答

### 1. 如果客户端不发送 Content-Length 怎么办

HTTP/1.1 协议强制要求请求必须包含 `Content-Length` 或使用 `Transfer-Encoding: chunked`。如果两者都没有，服务器会返回 411（Length Required）错误。

对于 `Transfer-Encoding: chunked` 的请求，Tomcat 会边读边解析，一旦累计读取的数据超过限制，立即停止并返回错误。

### 2. 如果客户端伪造 Content-Length 怎么办

比如客户端声明 `Content-Length: 10MB`，但实际发送了 100MB，会怎样？

Tomcat 会在实际读取时检查，读取量超过声明值后会断开连接。具体行为：

- 如果声明 10MB，实际发送 100MB，Tomcat 读取到 10MB 后发现还有数据，会断开连接

- 客户端会收到连接重置错误（Connection reset by peer）

- 服务器不会继续读取剩余的 90MB

## 小结

这篇文档从底层原理出发，讲清楚了 Spring Boot 文件上传大小限制的机制。核心要点：

- 1.
**常见误解是错的**：Spring Boot 不会把超限文件全部加载到内存再拒绝，而是有完善的早期拒绝机制

- 2.
**HTTP 协议是基础**：`Content-Length` 请求头让服务器在读取请求体之前就知道请求大小，这是早期拒绝的基础

- 3.
**Tomcat 层的早期拒绝**：Tomcat 在解析请求头时检查 `Content-Length`，超过 `maxSwallowSize`（默认 2MB）直接拒绝，不读取请求体

- 4.
**Spring Boot 层的边读边检查**：Spring Boot 在解析 multipart 请求时，边读边检查文件大小，超过 `max-file-size` 立即停止并抛出异常

- 5.
**流式处理 + 临时文件**：即使文件没超限，Spring Boot 也不会把整个文件加载到内存，而是边读边写到临时文件，内存占用只有一个小的缓冲区（8KB）

- 6.
**实战验证**：通过 Ragent 项目的实际测试，验证了上传 1GB 文件时内存占用没有增长，早期拒绝机制确实生效

开发者可以放心配置文件上传大小限制，不用担心恶意用户通过上传超大文件来耗尽服务器内存。Spring Boot 和 Tomcat 的底层机制已经做好了防护。

不过即使做了单请求的文件大小验证，为了避免临时文件被大量写入，最好还是要能控制并发量。下一章节咱们就会提如何基于全局信号量机制做并发限流。

> Source: https://t.zsxq.com/pFmQ6
> Resolved: https://articles.zsxq.com/id_mw9s4cqz40gz.html
